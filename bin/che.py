#!/usr/bin/env python3
"""``che`` - the dispatcher every helper script in this repo hangs off.

Three ways in, all landing on the same command table in ``bin/commands.py``:

* ``che`` on its own opens a full-screen menu: type to filter, arrows to move,
  Enter to run. Commands that can preview default to preview. What the menu
  shows and how keys move it is ``bin/menu.py``; running what it picks is here.
* ``che <command> [args…]`` runs one directly, with the same environment the
  shell wrapper would have used, and ``exec``s so signals and exit codes pass
  straight through.
* ``che install|update|doctor|uninstall|list|completions`` manage the install
  itself - see ``bin/install.py`` and ``bin/doctor.py``.

The shell wrappers (``delete-by-ext``, ``sync-all-branches``, …) are generated
from the same table, so anything reachable here is reachable by name too.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from contextlib import suppress
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import art
import doctor
import install
import machine
import menu
import shellgen
import tui
from commands import (
    CATEGORIES,
    VERSION,
    Command,
    Resolved,
    all_commands,
    command_names,
    grouped,
    resolve,
    variants,
)
from utils import add_bool_flag, build_parser, note, parse_bool, run, run_cli, success, warning

__version__ = VERSION


@lru_cache(maxsize=1)
def _interpreter() -> str:
    """The python the scripts run under.

    Normally this very interpreter: the shell wrapper already chose
    ``$CHE_PYTHON``. Through the npm ``bin`` link, though, ``che`` starts under
    whatever ``python3`` is first on PATH, which on a stock Mac is the years-old
    Command Line Tools build. The dispatcher itself tolerates that; the scripts
    do not, so hand them the newest suitable interpreter instead.
    """
    return machine.find_python()[0]


# ---------------------------------------------------------------------------
# Running a command
# ---------------------------------------------------------------------------


def _argv_env(resolved: Resolved, extra: list[str]) -> tuple[list[str], dict[str, str]]:
    """The argv and environment overrides that run ``resolved`` as its wrapper would.

    A built-in runs as ``che <name>`` in a child, so the menu reaches it the
    same way it reaches a script: prompts, the destructive confirm, ``--help``.
    """
    command = resolved.command
    if command.builtin:
        return [_interpreter(), str(Path(__file__).resolve()), command.name, *extra], {}
    return [_interpreter(), str(command.path), *resolved.args, *extra], resolved.env


def _missing_script(command: Command) -> bool:
    if command.script and not command.path.exists():
        warning(f"❌ Missing script: {command.path}")
        return True
    return False


def exec_command(resolved: Resolved, extra: list[str]) -> int:
    """Replace this process with the script, the way the wrapper would.

    ``exec`` rather than a subprocess so Ctrl-C, job control and the exit code
    behave exactly as if the script had been called directly - which matters
    for the long-running ones (``ping-nas``) and the full-screen ones
    (``btop``).
    """
    if _missing_script(resolved.command):
        return 127
    argv, env = _argv_env(resolved, extra)
    os.execvpe(argv[0], argv, {**os.environ, **env})  # noqa: S606
    return 127  # unreachable: execvpe only returns by raising


def run_command(resolved: Resolved, extra: list[str]) -> int:
    """Run a command as a child, for the menu (which needs to come back).

    Ctrl-C reaches the child through the terminal, and is the only way to stop
    ``ping-nas`` or ``all-actions --watch``. It must not take the menu down
    too, so the menu ignores it and waits for the child to decide what it means.
    """
    if _missing_script(resolved.command):
        return 127
    argv, env = _argv_env(resolved, extra)
    with subprocess.Popen(argv, env={**os.environ, **env}) as child:  # noqa: S603
        while child.returncode is None:
            with suppress(KeyboardInterrupt):
                child.wait()
    # A child killed by signal N reports -N; a shell would say 128+N.
    return 128 - child.returncode if child.returncode < 0 else child.returncode


def script_help(command: Command) -> str:
    argv, env = _argv_env(Resolved(command), ["--help"])
    try:
        result = run(argv, capture=True, check=False, env={**env, "NO_COLOR": "1"}, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"(could not read help: {exc})"
    return (result.stdout or result.stderr).strip()


# ---------------------------------------------------------------------------
# Help and listing
# ---------------------------------------------------------------------------


def usage() -> None:
    colors = tui.palette()
    print(f"{colors.bold}che{colors.reset} {colors.grey}v{VERSION}{colors.reset} - shell helpers")
    print()
    print(f"{colors.bold}USAGE{colors.reset}")
    print("  che                        open the interactive menu")
    print("  che <command> [args…]      run one command")
    print("  che help <command>         show that command's own --help")
    print()

    for category, members in grouped(all_commands()):
        print(
            f"{colors.bold}{category.title.upper()}{colors.reset} {colors.grey}{category.blurb}{colors.reset}"
        )
        width = max(len(command.name) for command in members) + 2
        for command in members:
            marks = ""
            if command.has_dry_twin:
                marks = f" {colors.grey}(+{command.dry_name}){colors.reset}"
            print(f"  {colors.cyan}{command.name:<{width}}{colors.reset}{command.summary}{marks}")
        print()

    print(f"{colors.bold}OPTIONS{colors.reset}")
    print("  -h, --help                 show this help")
    print("  -v, --version              show the version")
    print()
    print(
        f"{colors.grey}Every command outside CHE is also a shell function of the same name."
        f"{colors.reset}"
    )


def list_commands(category: str = "", *, as_json: bool = False, include_dry: bool = True) -> int:
    known = [item.key for item in CATEGORIES]
    if category and category not in known:
        warning(f"❌ Unknown category: {category}")
        note(f"   Known: {', '.join(known)}")
        return 1

    chosen = [
        command
        for group, members in grouped(all_commands())
        if not category or group.key == category
        for command in members
    ]

    if as_json:
        payload = [
            {
                "name": command.name,
                "category": command.category,
                "summary": command.summary,
                "script": command.script,
                "needs": list(command.needs),
                "flags": list(command.flag_names),
                "destructive": command.destructive,
                "dry_run": command.dry_run,
            }
            for command in chosen
        ]
        print(json.dumps(payload, indent=2))
        return 0

    for variant in variants(chosen):
        if include_dry or not variant.dry:
            print(variant.name)
    return 0


def list_main(argv: list[str] | None = None) -> int:
    parser = build_parser(prog="che list", description="📋 List every command.")
    parser.add_argument("--category", default="", metavar="NAME", help="Only this category")
    add_bool_flag(parser, "--json", help="Machine-readable output")
    add_bool_flag(parser, "--no-dry", allow_value=False, help="Hide the -dr twins")
    args = parser.parse_args(argv)
    return list_commands(args.category, as_json=args.json, include_dry=not args.no_dry)


# ---------------------------------------------------------------------------
# The interactive menu
# ---------------------------------------------------------------------------


def run_menu() -> int:
    """The full-screen browser. Returns the exit status of the last command."""
    if not tui.is_interactive():
        warning("❌ The menu needs a terminal. Try `che <command>` or `che --help`.")
        return 1

    state = menu.Menu()
    last_status = 0
    screen = tui.Screen()

    with tui.Term() as term:
        while True:
            screen.start()
            menu.draw(screen, state)
            screen.flush()

            key = tui.read_key(timeout=0.5)
            if key is None:
                continue  # timeout: loop so a resize repaints

            action = menu.handle_key(state, key)
            if action == "quit":
                break
            if not action or (target := state.resolved()) is None:
                continue

            term.suspend()
            if action == "help":
                show_help(target.command)
            else:
                last_status = launch(target, prompt=(action == "run"))
            tui.pause("Press any key to go back")
            term.resume()

    return last_status


class Cancelled(Exception):
    """The user backed out before the command ran. The message says why, if anything."""


def launch(target: Resolved, *, prompt: bool) -> int:
    """Collect arguments for ``target``, confirm a real run, and run it."""
    command = target.command
    colors = tui.palette()

    print()
    print(
        f"{colors.bright_magenta}{colors.bold}{target.name}{colors.reset}  "
        f"{colors.grey}{command.summary}{colors.reset}"
    )
    print()

    try:
        extra = collect_arguments(command) if prompt else []
        # What a person would type to repeat this exactly, so it is safe to
        # copy: the -dr twin carries its own preview, whichever style it uses.
        print()
        print(f"{colors.grey}$ {shlex.join(['che', target.name, *extra])}{colors.reset}")

        if command.destructive and not effective_dry(target.dry, extra):
            print()
            if not tui.confirm(f"{command.name} changes files for real. Continue?", default=False):
                raise Cancelled
    except (Cancelled, KeyboardInterrupt) as exc:
        if str(exc):
            warning(f"❌ {exc}")
        print(f"\n{colors.yellow}Cancelled.{colors.reset}")
        return 130

    print()
    status = run_command(target, extra)
    print()
    if status == 0:
        success(f"✓ {target.name} finished")
    else:
        warning(f"✗ {target.name} exited {status}")
    return status


def effective_dry(dry: bool, extra: list[str]) -> bool:
    """Whether a run only previews, once a ``--dry-run`` typed by hand is counted.

    Read the way the script's own parser reads it - ``utils.parse_bool``, the
    last one winning, nothing after ``--`` - so ``--dry-run=0`` gets the
    "changes files for real" question, and so does a ``--dry-run=false`` that
    overrides the ``DRY_RUN=true`` of a command left on preview.
    """
    for arg in extra:
        if arg == "--":
            break
        flag, sep, value = arg.partition("=")
        if flag == "--dry-run":
            try:
                dry = parse_bool(value) if sep else True
            except ValueError:
                dry = False  # the script will reject it; ask anyway
    return dry


def collect_arguments(command: Command) -> list[str]:
    """Ask the curated questions for ``command``, then for anything extra.

    Raises :class:`Cancelled` for a required answer left empty, or extra
    arguments that do not split (an unclosed quote).
    """
    if not command.prompts:
        return []

    extra: list[str] = []
    for prompt in command.prompts:
        if prompt.kind == "bool":
            default = prompt.default == "true"
            answer = tui.confirm(prompt.label, default=default)
            # Only pass the flag when the answer differs from what the script
            # already does, so the command line stays as short as what a person
            # would have typed.
            if answer and not default:
                extra.append(prompt.flag)
            elif not answer and default:
                extra.append(f"{prompt.flag}=false")
            continue

        answer = tui.ask(
            prompt.label + (f" ({prompt.help})" if prompt.help else ""),
            default=prompt.default,
            kind=prompt.kind,
            choices=prompt.choices,
            history_file=history_file(prompt.key),
        )
        if not answer:
            if prompt.required:
                raise Cancelled(f"{prompt.label} is required.")
            continue

        extra.append(answer if not prompt.flag else f"{prompt.flag}={answer}")

    free = tui.ask("Extra arguments", default="", history_file=history_file("extra"))
    try:
        extra += shlex.split(free)
    except ValueError as exc:
        raise Cancelled(f"Extra arguments: {exc}") from None
    return extra


def history_file(key: str) -> Path:
    return machine.state_dir() / f"history-{key}"


def show_help(command: Command) -> None:
    colors = tui.palette()
    print()
    print(script_help(command))
    print()
    for binary in command.needs:
        if not shutil.which(binary):
            warning(f"missing: {binary} - {machine.INSTALL_HINTS.get(binary, 'not installed')}")
    print(f"{colors.grey}(from `{command.name} --help`){colors.reset}")


# ---------------------------------------------------------------------------
# Built-in subcommands
# ---------------------------------------------------------------------------


def completions_main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="che completions",
        description="⌨️ Print the completion script for a shell.",
        epilog="`che install` already wires these up; this is for sourcing one by hand.",
    )
    parser.add_argument("shell", nargs="?", choices=shellgen.FLAVORS, help="The shell")
    parser.add_argument(
        "--shell", dest="shell_flag", choices=shellgen.FLAVORS, metavar="NAME", help="The same"
    )
    args = parser.parse_args(argv)
    shell = args.shell_flag or args.shell
    if not shell:
        parser.error("a shell is required")
    print(shellgen.completions(shell), end="")
    return 0


# Each built-in's CLI sits beside what it runs and parses only its own flags.
BUILTIN_MAIN: dict[str, Callable[[list[str]], int]] = {
    "install": install.install_main,
    "update": install.update_main,
    "doctor": doctor.doctor_main,
    "uninstall": install.uninstall_main,
    "list": list_main,
    "completions": completions_main,
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def first_run() -> int:
    """What ``che`` does on a machine where it has never been installed."""
    colors = tui.palette()
    art.print_logo(f"shell helpers, v{VERSION}")
    print(f"  {colors.grey}che is not installed in this shell yet.{colors.reset}")
    print()
    print(
        f"  {colors.bold}i{colors.reset}  install it now (writes a block into your shell rc file)"
    )
    print(f"  {colors.bold}m{colors.reset}  just open the menu")
    print(f"  {colors.bold}q{colors.reset}  quit")
    print()

    with tui.Term(alt_screen=False):
        key = tui.read_key()

    print()
    if key in ("i", "enter"):
        return install.install_main([])
    if key == "m":
        return run_menu()
    return 0


def main() -> int:
    argv = sys.argv[1:]

    if not argv:
        if not tui.is_interactive():
            usage()
            return 0
        if machine.load_record() is None:
            return first_run()
        return run_menu()

    first = argv[0]
    rest = argv[1:]

    if first in ("-h", "--help"):
        usage()
        return 0
    if first in ("-v", "--version", "version"):
        print(f"che {VERSION}")
        return 0
    if first == "help":
        if not rest:
            usage()
            return 0
        found = resolve(rest[0])
        if found is None:
            return unknown(rest[0])
        print(script_help(found.command))
        return 0
    if first == "menu":
        return run_menu()

    if first in BUILTIN_MAIN:
        return BUILTIN_MAIN[first](rest)

    found = resolve(first)
    if found is None:
        return unknown(first)

    return exec_command(found, rest)


def suggest(name: str, *, limit: int = 3) -> list[str]:
    """Closest known command names, for the "did you mean" line."""
    pool = command_names()
    close = get_close_matches(name, pool, n=limit, cutoff=0.6)
    if close:
        return close
    # get_close_matches misses substring typos like "codecs" for "show-codecs".
    return [candidate for candidate in pool if name and name in candidate][:limit]


def unknown(name: str) -> int:
    warning(f"❌ Unknown command: {name}")
    close = suggest(name)
    if close:
        note("   Did you mean: " + ", ".join(close))
    note("   `che --help` lists everything, `che` opens the menu.")
    return 1


if __name__ == "__main__":
    run_cli(main)
