#!/usr/bin/env python3
"""``che`` - the dispatcher every helper script in this repo hangs off.

Three ways in, all landing on the same command table in ``bin/commands.py``:

* ``che`` on its own opens a full-screen menu: type to filter, arrows to move,
  Enter to run. Commands that can preview default to preview.
* ``che <command> [args…]`` runs one directly, with the same environment the
  shell wrapper would have used, and ``exec``s so signals and exit codes pass
  straight through.
* ``che install|update|doctor|uninstall|list|completions`` manage the install
  itself - see ``bin/install.py``.

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
import textwrap
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import install as installer
import shellgen
import tui
from commands import (
    BUILTIN_NAMES,
    CATEGORIES,
    MENU_KEYS,
    REPO,
    VERSION,
    Command,
    Resolved,
    all_commands,
    fuzzy_match,
    in_category,
    resolve,
    suggest,
)
from utils import note, run_cli, success, warning

__version__ = VERSION

BIN = REPO / "bin"


@lru_cache(maxsize=64)
def _which(binary: str) -> str | None:
    """PATH lookup, cached: the menu asks about the same binaries every frame."""
    return shutil.which(binary)


# ---------------------------------------------------------------------------
# Running a command
# ---------------------------------------------------------------------------


def build_argv(command: Command, extra: list[str], *, dry: bool = False) -> list[str]:
    _, fixed = command.invocation(dry=dry)
    return [sys.executable, str(BIN / command.script), *fixed, *extra]


def command_env(command: Command, *, dry: bool = False) -> dict[str, str]:
    env, _ = command.invocation(dry=dry)
    return {**os.environ, **env}


def exec_command(resolved: Resolved, extra: list[str]) -> int:
    """Replace this process with the script, the way the wrapper would.

    ``exec`` rather than a subprocess so Ctrl-C, job control and the exit code
    behave exactly as if the script had been called directly - which matters
    for the long-running ones (``ping-nas``) and the full-screen ones
    (``btop``).
    """
    command = resolved.command

    if command.body:
        # A shell-only wrapper (`list-permission`). Nothing to exec but sh.
        return subprocess.run(  # noqa: S603 - fixed body from the manifest, args via $@
            ["sh", "-c", command.body + ' "$@"', command.name, *extra],  # noqa: S607
            check=False,
        ).returncode

    script = BIN / command.script
    if not script.exists():
        warning(f"❌ Missing script: {script}")
        return 127

    argv = build_argv(command, extra, dry=resolved.dry)
    os.execve(argv[0], argv, command_env(command, dry=resolved.dry))  # noqa: S606
    return 127  # unreachable: execve only returns by raising


def run_command(resolved: Resolved, extra: list[str]) -> int:
    """Run a command as a child, for the menu (which needs to come back)."""
    command = resolved.command

    if command.body:
        return subprocess.run(  # noqa: S603 - fixed body from the manifest, args via $@
            ["sh", "-c", command.body + ' "$@"', command.name, *extra],  # noqa: S607
            check=False,
        ).returncode

    return subprocess.run(  # noqa: S603 - argv list, shell=False
        build_argv(command, extra, dry=resolved.dry),
        env=command_env(command, dry=resolved.dry),
        check=False,
    ).returncode


def script_help(command: Command) -> str:
    if not command.script:
        return command.summary
    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(BIN / command.script), "--help"],
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ, "NO_COLOR": "1"},
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"(could not read help: {exc})"
    return (result.stdout or result.stderr).strip()


# ---------------------------------------------------------------------------
# Help
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

    for category in CATEGORIES:
        members = in_category(category.key)
        if not members:
            continue
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
        f"{colors.grey}Every command above is also a shell function of the same name.{colors.reset}"
    )


def list_commands(category: str = "", *, as_json: bool = False, include_dry: bool = True) -> int:
    if as_json:
        payload = [
            {
                "name": command.name,
                "category": command.category,
                "summary": command.summary,
                "script": command.script,
                "needs": list(command.needs),
                "flags": list(command.flags),
                "destructive": command.destructive,
                "dry_run": command.dry_run,
            }
            for command in all_commands()
            if not category or command.category == category
        ]
        print(json.dumps(payload, indent=2))
        return 0

    if category and not any(command.category == category for command in all_commands()):
        warning(f"❌ Unknown category: {category}")
        note(f"   Known: {', '.join(item.key for item in CATEGORIES)}")
        return 1

    for command in all_commands():
        if category and command.category != category:
            continue
        print(command.name)
        if include_dry and command.has_dry_twin:
            print(command.dry_name)
    return 0


# ---------------------------------------------------------------------------
# The interactive menu
# ---------------------------------------------------------------------------


@dataclass
class Row:
    """One line in the menu list: either a category header or a command."""

    kind: str  # "header" | "item"
    text: str
    command: Command | None = None


@dataclass
class Menu:
    query: str = ""
    searching: bool = False
    cursor: int = 0
    offset: int = 0
    dry: dict[str, bool] = field(default_factory=dict)
    show_help: bool = False
    status: str = ""

    def matches(self) -> list[Command]:
        scored = []
        for command in all_commands():
            score = fuzzy_match(self.query, command)
            if score is None:
                continue
            scored.append((score, command))
        scored.sort(key=lambda pair: (pair[0], pair[1].category, pair[1].name))
        return [command for _, command in scored]

    def rows(self) -> list[Row]:
        commands = self.matches()
        rows: list[Row] = []
        if self.query:
            rows.extend(Row("item", command.name, command) for command in commands)
            return rows

        for category in CATEGORIES:
            members = [command for command in commands if command.category == category.key]
            if not members:
                continue
            rows.append(Row("header", f"{category.title}  {category.blurb}"))
            rows.extend(Row("item", command.name, command) for command in members)
        return rows

    def items(self) -> list[int]:
        return [index for index, row in enumerate(self.rows()) if row.kind == "item"]

    def selected(self) -> Command | None:
        rows = self.rows()
        if not rows:
            return None
        self.cursor = max(0, min(self.cursor, len(rows) - 1))
        row = rows[self.cursor]
        return row.command

    def move(self, delta: int) -> None:
        rows = self.rows()
        items = [index for index, row in enumerate(rows) if row.kind == "item"]
        if not items:
            return
        if self.cursor not in items:
            self.cursor = items[0]
            return
        position = items.index(self.cursor)
        self.cursor = items[(position + delta) % len(items)]

    def first(self) -> None:
        items = self.items()
        self.cursor = items[0] if items else 0

    def last(self) -> None:
        items = self.items()
        self.cursor = items[-1] if items else 0

    def is_dry(self, command: Command) -> bool:
        # Anything that can preview previews first: the menu is a browsing UI,
        # and "I pressed Enter to see what it does" should never delete files.
        return self.dry.get(command.name, command.has_dry_twin)


HELP_OVERLAY = MENU_KEYS


def menu() -> int:
    """The full-screen browser. Returns the exit status of the last command."""
    if not tui.is_interactive():
        warning("❌ The menu needs a terminal. Try `che <command>` or `che --help`.")
        return 1

    state = Menu()
    state.first()
    last_status = 0
    screen = tui.Screen()

    with tui.Term() as term:
        while True:
            screen.start()
            draw(screen, state)
            screen.flush()

            key = tui.read_key(timeout=0.5)
            if key is None:
                continue  # timeout: loop so a resize repaints

            if state.show_help:
                state.show_help = False
                continue

            action = handle_key(state, key)

            if action == "quit":
                break
            if action == "run" or action == "run-raw":
                command = state.selected()
                if command is None:
                    continue
                term.suspend()
                last_status = launch(command, state, prompt=(action == "run"))
                term.resume()
            elif action == "help":
                command = state.selected()
                if command is None:
                    continue
                term.suspend()
                show_help(command)
                term.resume()

    return last_status


def handle_key(state: Menu, key: str) -> str:
    """Fold one keypress into the menu state. Returns an action for the caller."""
    if state.searching:
        if key == "enter":
            state.searching = False
        elif key == "esc":
            state.searching = False
            state.query = ""
            state.first()
        elif key == "backspace":
            state.query = state.query[:-1]
            state.first()
        elif key == "ctrl-u":
            state.query = ""
            state.first()
        elif key in ("up", "down"):
            state.move(-1 if key == "up" else 1)
        elif key == "ctrl-c":
            return "quit"
        elif len(key) == 1 and key.isprintable():
            state.query += key
            state.first()
        return ""

    if key in ("q", "ctrl-c", "eof"):
        return "quit"
    if key == "esc":
        if state.query:
            state.query = ""
            state.first()
            return ""
        return "quit"
    if key in ("up", "k"):
        state.move(-1)
    elif key in ("down", "j"):
        state.move(1)
    elif key == "pgup":
        for _ in range(10):
            state.move(-1)
    elif key == "pgdn":
        for _ in range(10):
            state.move(1)
    elif key in ("home", "g"):
        state.first()
    elif key in ("end", "G"):
        state.last()
    elif key == "/":
        state.searching = True
    elif key == "?":
        state.show_help = True
    elif key == "d":
        command = state.selected()
        if command and command.has_dry_twin:
            state.dry[command.name] = not state.is_dry(command)
            state.status = f"dry-run {'on' if state.is_dry(command) else 'OFF'} for {command.name}"
        elif command:
            state.status = f"{command.name} has no preview mode"
    elif key == "h":
        return "help"
    elif key == "x":
        return "run-raw"
    elif key == "enter":
        return "run"
    elif len(key) == 1 and key.isprintable():
        # Typing anything else drops into search, the way a file picker does.
        state.searching = True
        state.query += key
        state.first()
    return ""


def draw(screen: tui.Screen, state: Menu) -> None:
    colors = tui.palette()
    width = screen.columns

    total = len(all_commands())
    shown = len(state.matches())
    title = f"{colors.bright_magenta}{colors.bold}che{colors.reset}"
    counter = f"{shown}/{total}" if state.query else str(total)
    header = (
        f"  {title} {colors.grey}v{VERSION}{colors.reset}  "
        f"{colors.grey}{counter} commands{colors.reset}"
    )
    screen.line()
    screen.line(header)

    if state.searching or state.query:
        caret = f"{colors.cyan}▏{colors.reset}" if state.searching else " "
        screen.line(f"  {colors.grey}search{colors.reset} {caret}{state.query}")
    else:
        screen.line(f"  {colors.grey}type to search   ↑↓ move   ⏎ run   ? keys{colors.reset}")
    screen.line(f"  {colors.grey}{'─' * max(0, width - 4)}{colors.reset}")

    if state.show_help:
        draw_help(screen)
        return

    body_rows = max(3, screen.rows - 8)
    rows = state.rows()
    if not rows:
        screen.line()
        screen.line(f"  {colors.yellow}No command matches {state.query!r}{colors.reset}")
        draw_footer(screen, state)
        return

    # Keep the cursor inside the viewport, with a line of context either side.
    if state.cursor < state.offset + 1:
        state.offset = max(0, state.cursor - 1)
    if state.cursor >= state.offset + body_rows - 1:
        state.offset = min(max(0, len(rows) - body_rows), state.cursor - body_rows + 2)

    detail_width = 0
    if width >= 92:
        detail_width = max(34, width // 2 - 6)
    list_width = width - detail_width - (4 if detail_width else 2)

    detail_lines = detail_pane(state, detail_width) if detail_width else []

    for index in range(state.offset, min(len(rows), state.offset + body_rows)):
        row = rows[index]
        if row.kind == "header":
            left = tui.fit(f"  {colors.bold}{colors.blue}{row.text}{colors.reset}", list_width)
        else:
            command = row.command
            if command is None:
                continue
            selected = index == state.cursor
            pointer = f"{colors.cyan}▸{colors.reset}" if selected else " "
            name = command.name
            if selected:
                name = f"{colors.bold}{colors.cyan}{name}{colors.reset}"
            elif command.destructive:
                name = f"{colors.yellow}{name}{colors.reset}"

            badge = ""
            if command.has_dry_twin and state.is_dry(command):
                badge = f" {colors.grey}·dry{colors.reset}"
            elif command.destructive:
                badge = f" {colors.red}·live{colors.reset}"

            left = f"  {pointer} {command.icon} {name}{badge}"
            if detail_width:
                left += " " * max(0, list_width - tui.display_width(left))
            else:
                room = max(0, list_width - tui.display_width(left) - 2)
                summary = tui.truncate(command.summary, room)
                left += f"  {colors.grey}{summary}{colors.reset}"

        detail_index = index - state.offset
        right = detail_lines[detail_index] if detail_index < len(detail_lines) else ""
        if detail_width:
            screen.line(f"{left}{colors.grey}│{colors.reset} {right}")
        else:
            screen.line(left)

    draw_footer(screen, state)


def detail_pane(state: Menu, width: int) -> list[str]:
    """The right-hand column: what the selected command is and what it needs."""
    colors = tui.palette()
    command = state.selected()
    if command is None:
        return []

    lines: list[str] = [f"{colors.bold}{command.name}{colors.reset}", ""]
    lines += wrap(command.summary, width, colors.grey)
    lines.append("")

    def field_line(label: str, value: str) -> str:
        return f"{colors.grey}{label:<8}{colors.reset}{value}"

    if command.script:
        lines.append(field_line("script", f"bin/{command.script}"))
    elif command.builtin:
        lines.append(field_line("script", "built in to che"))

    if command.needs:
        parts = []
        for binary in command.needs:
            found = _which(binary)
            mark = f"{colors.green}✓{colors.reset}" if found else f"{colors.red}✗{colors.reset}"
            parts.append(f"{mark} {binary}")
        lines.append(field_line("needs", "  ".join(parts)))

    if command.flags:
        lines += wrap(" ".join(command.flags), width - 8, colors.grey, indent="flags   ")

    if command.has_dry_twin:
        state_text = (
            f"{colors.green}on{colors.reset} - previews only"
            if state.is_dry(command)
            else f"{colors.red}OFF{colors.reset} - changes files"
        )
        lines.append(field_line("dry-run", f"{state_text}  {colors.grey}(d){colors.reset}"))
    elif command.destructive:
        reason = command.no_preview_reason or "changes files"
        lines += wrap(reason, width - 8, colors.yellow, indent="warning ")

    if command.setup:
        lines += wrap(command.setup, width - 8, colors.yellow, indent="setup   ")

    if command.macos_only:
        lines.append(field_line("os", "macOS only"))

    lines.append("")
    lines.append(f"{colors.grey}⏎ run   x run bare   h help{colors.reset}")
    return [tui.truncate(line, width) for line in lines]


def wrap(text: str, width: int, color: str = "", indent: str = "") -> list[str]:
    colors = tui.palette()
    body = textwrap.wrap(text, max(10, width - len(indent))) or [""]
    out = []
    for index, line in enumerate(body):
        prefix = indent if index == 0 else " " * len(indent)
        out.append(
            f"{colors.grey}{prefix}{colors.reset}{color}{line}{colors.reset if color else ''}"
        )
    return out


def draw_help(screen: tui.Screen) -> None:
    colors = tui.palette()
    screen.line()
    screen.line(f"  {colors.bold}Keys{colors.reset}")
    screen.line()
    width = max(len(key) for key, _ in HELP_OVERLAY) + 3
    for key, description in HELP_OVERLAY:
        screen.line(
            f"    {colors.cyan}{key:<{width}}{colors.reset}{colors.grey}{description}{colors.reset}"
        )
    screen.line()
    screen.line(f"  {colors.grey}Press any key to go back.{colors.reset}")


def draw_footer(screen: tui.Screen, state: Menu) -> None:
    colors = tui.palette()
    screen.pad_to(screen.rows - 2)
    screen.line(f"  {colors.grey}{'─' * max(0, screen.columns - 4)}{colors.reset}")
    if state.status:
        screen.line(f"  {colors.yellow}{state.status}{colors.reset}")
        state.status = ""
    else:
        screen.line(
            f"  {colors.grey}⏎ run   d dry-run   h help   / search   ? keys   q quit{colors.reset}"
        )


# ---------------------------------------------------------------------------
# Running from the menu
# ---------------------------------------------------------------------------


def launch(command: Command, state: Menu, *, prompt: bool = True) -> int:
    """Collect arguments for ``command``, run it, and wait for a keypress."""
    colors = tui.palette()
    dry = state.is_dry(command)

    print()
    print(
        f"{colors.bright_magenta}{colors.bold}{command.name}{colors.reset}  {colors.grey}{command.summary}{colors.reset}"
    )
    print()

    if command.builtin:
        status = run_builtin(command.name, [])
        tui.pause("Press any key to go back")
        return status

    extra: list[str] = []
    if prompt and command.prompts:
        collected = collect_arguments(command)
        if collected is None:
            print(f"{colors.yellow}Cancelled.{colors.reset}")
            tui.pause("Press any key to go back")
            return 130
        extra = collected

        free = tui.ask("Extra arguments", default="", history_file=history_file("extra"))
        if free.strip():
            extra += shlex.split(free)

    resolved = Resolved(command, dry=dry, matched=command.name)
    preview = " ".join([command.name, *extra])
    env, _ = command.invocation(dry=dry)
    env_text = " ".join(f"{key}={value}" for key, value in sorted(env.items()))

    print()
    print(f"{colors.grey}$ {env_text} {preview}{colors.reset}".replace("$  ", "$ "))

    previewing = dry or any(
        arg.startswith("--dry-run") and not arg.endswith("=false") for arg in extra
    )
    if command.destructive and not previewing:
        print()
        if not tui.confirm(f"{command.name} changes files for real. Continue?", default=False):
            print(f"{colors.yellow}Cancelled.{colors.reset}")
            tui.pause("Press any key to go back")
            return 130

    print()
    status = run_command(resolved, extra)
    print()
    if status == 0:
        success(f"✓ {command.name} finished")
    else:
        warning(f"✗ {command.name} exited {status}")

    tui.pause("Press any key to go back")
    return status


def collect_arguments(command: Command) -> list[str] | None:
    """Ask the curated questions for ``command``. ``None`` means cancelled."""
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
                warning(f"❌ {prompt.label} is required.")
                return None
            continue

        extra.append(answer if not prompt.flag else f"{prompt.flag}={answer}")

    return extra


def history_file(key: str) -> Path:
    return installer.state_dir() / f"history-{key}"


def show_help(command: Command) -> None:
    colors = tui.palette()
    print()
    text = script_help(command)
    print(text)
    print()
    if command.needs:
        for binary in command.needs:
            if not _which(binary):
                warning(
                    f"missing: {binary} - {installer.INSTALL_HINTS.get(binary, 'not installed')}"
                )
    print(f"{colors.grey}(from `{command.name} --help`){colors.reset}")
    tui.pause("Press any key to go back")


# ---------------------------------------------------------------------------
# Built-in subcommands
# ---------------------------------------------------------------------------


def run_builtin(name: str, argv: list[str]) -> int:
    if name == "install":
        return installer.install_main(argv)
    if name == "update":
        parser = _simple_parser("che update", "⬆️  Update the scripts, then refresh the wrappers.")
        args = parser.parse_args(argv)
        return installer.update(check_only=args.check, dry_run=args.dry_run)
    if name == "doctor":
        parser = _simple_parser("che doctor", "🩺 Check the install and everything it depends on.")
        args = parser.parse_args(argv)
        return installer.doctor(as_json=args.json, verbose=args.verbose)
    if name == "uninstall":
        parser = _simple_parser("che uninstall", "🧽 Remove the wrappers, shim and completions.")
        args = parser.parse_args(argv)
        return installer.uninstall(dry_run=args.dry_run, purge=args.purge)
    if name == "list":
        parser = _simple_parser("che list", "📋 List every command.")
        args = parser.parse_args(argv)
        return list_commands(args.category, as_json=args.json, include_dry=not args.no_dry)
    if name == "completions":
        return completions_main(argv)
    raise AssertionError(f"unhandled builtin: {name}")


def _simple_parser(prog: str, description: str):
    from utils import add_bool_flag, build_parser

    parser = build_parser(prog=prog, description=description)
    add_bool_flag(parser, "--dry-run", help="Report what would change, change nothing")
    add_bool_flag(parser, "--check", help="Report whether an update is available, apply nothing")
    add_bool_flag(parser, "--json", help="Machine-readable output")
    add_bool_flag(parser, "--verbose", help="Include checks that passed")
    add_bool_flag(parser, "--purge", help="Also delete ~/.config/che")
    add_bool_flag(parser, "--no-dry", dest="no_dry", allow_value=False, help="Hide the -dr twins")
    parser.add_argument("--category", default="", metavar="NAME", help="Only this category")
    return parser


def completions_main(argv: list[str]) -> int:
    shells = ", ".join(shellgen.SHELLS)
    if not argv or argv[0] in ("-h", "--help"):
        print(f"Usage: che completions <{shells.replace(', ', '|')}>")
        print()
        print("Print the completion script for a shell. `che install` already")
        print("wires these up; this is for sourcing one by hand.")
        return 0 if argv else 1

    shell = argv[0].removeprefix("--shell=")
    if shell not in shellgen.SHELLS:
        warning(f"❌ Unknown shell: {shell}")
        note(f"   Known: {shells}")
        return 1
    print(shellgen.completions(shell), end="")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def first_run() -> int:
    """What ``che`` does on a machine where it has never been installed."""
    colors = tui.palette()
    installer.print_logo(f"shell helpers, v{VERSION}")
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
        return installer.wizard()
    if key == "m":
        return menu()
    return 0


def main() -> int:
    argv = sys.argv[1:]

    if not argv:
        if not tui.is_interactive():
            usage()
            return 0
        if not installer.load_config():
            return first_run()
        return menu()

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
        return menu()

    if first in BUILTIN_NAMES:
        return run_builtin(first, rest)

    found = resolve(first)
    if found is None:
        return unknown(first)

    return exec_command(found, rest)


def unknown(name: str) -> int:
    warning(f"❌ Unknown command: {name}")
    close = suggest(name)
    if close:
        note("   Did you mean: " + ", ".join(close))
    note("   `che --help` lists everything, `che` opens the menu.")
    return 1


if __name__ == "__main__":
    run_cli(main)
