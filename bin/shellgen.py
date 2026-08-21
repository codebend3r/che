"""Render the shell wrappers and completions from :mod:`commands`.

Everything under ``shell/`` is produced here, and ``che install`` writes the
result to disk. Two rules keep the generated files honest:

* **No machine-specific data.** These files are committed, so they must work
  from any clone path. The one machine-specific thing - where the repo lives
  and which ``python3`` to use - goes in the small block the installer writes
  into ``~/.zshrc``, not here. As a fallback the wrappers resolve their own
  location, so sourcing ``shell/che.zsh`` directly works with no block at all.
* **Deterministic.** ``che install --check`` re-renders and diffs against the
  files on disk, and CI runs that check, so generation may not depend on the
  environment it runs in.

Library module: no shebang, not executable.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from commands import (
    BUILTINS,
    CATEGORIES,
    COMMANDS,
    MENU_KEYS,
    VERSION,
    Command,
    required_binaries,
)

SHELLS = ("zsh", "bash", "fish")

# Where each shell's generated file lives, relative to the repo root.
WRAPPER_FILES = {
    "zsh": Path("shell/che.zsh"),
    "bash": Path("shell/che.bash"),
    "fish": Path("shell/che.fish"),
}
COMPLETION_FILES = {
    "zsh": Path("shell/completions/_che"),
    "bash": Path("shell/completions/che.bash"),
    "fish": Path("shell/completions/che.fish"),
}

# The rc-file block is delimited by these. Anything between them belongs to
# `che install` and is rewritten wholesale on every install; anything outside
# is the user's and is never touched.
BEGIN_MARKER = "# >>> che shell functions >>>"
END_MARKER = "# <<< che shell functions <<<"

# Flags that take a value, so completion can offer `--flag=` without a
# trailing space and then complete filenames after the `=`.
VALUE_FLAGS = frozenset(
    {
        "--author",
        "--category",
        "--exts",
        "--ext",
        "--ignore-words",
        "--interval",
        "--length",
        "--limit",
        "--only",
        "--owner",
        "--path",
        "--ping-timeout",
        "--pr-limit",
        "--protect",
        "--samples",
        "--shell",
        "--shells",
        "--size",
        "--sort",
        "--strategy",
        "--threshold",
        "--year",
    }
)

# Flags whose value is a path, so completion offers files rather than nothing.
PATH_FLAGS = frozenset({"--path"})


def _banner(comment: str = "#") -> str:
    return "\n".join(
        f"{comment} {line}".rstrip()
        for line in (
            f"che {VERSION} - generated file, do not edit.",
            "",
            "Generated from bin/commands.py by `che install`.",
            "To change a wrapper, edit that manifest and run `che install` again.",
        )
    )


def _flag_words(command: Command) -> list[str]:
    """Completion words for one command: its flags plus the universal ones."""
    words = [f"{flag}=" if flag in VALUE_FLAGS else flag for flag in command.flags]
    words.append("--help")
    return words


def _dry_variants(command: Command) -> list[tuple[str, bool]]:
    variants = [(command.name, False)]
    if command.has_dry_twin:
        variants.append((command.dry_name, True))
    return variants


# ---------------------------------------------------------------------------
# POSIX-family wrappers (zsh, bash, and anything else that speaks sh)
# ---------------------------------------------------------------------------


def _posix_body(command: Command, *, dry: bool) -> list[str]:
    """The body of one wrapper.

    DELIBERATE DIVERGENCE from the hand-written wrappers: every wrapper now
    forwards ``"$@"``. A few of them (clean-stale-branches, prune-worktrees)
    used to swallow their arguments, so ``clean-stale-branches --protect=x``
    silently ignored a flag the script documents.
    """
    env, args = command.invocation(dry=dry)
    prefix = "".join(f"{name}={shlex.quote(value)} " for name, value in sorted(env.items()))

    if command.body:
        call = command.body
    else:
        parts = ['"$CHE_PYTHON"', f'"$CHE_BIN/{command.script}"']
        parts += [shlex.quote(arg) for arg in args]
        parts.append('"$@"')
        call = prefix + " ".join(parts)

    sound = command.dry_sound if dry else command.sound
    lines = [f"  {call}"]
    if sound is not None:
        # `$?` is expanded before che_notify runs, so the wrapper still returns
        # the script's exit status. The old wrappers returned playsound's.
        lines.append(f"  che_notify {sound} $?")
    return lines


def _posix_wrappers() -> list[str]:
    lines: list[str] = []
    for category in CATEGORIES:
        members = [command for command in COMMANDS if command.category == category.key]
        if not members:
            continue
        lines += ["", f"# {'-' * 74}", f"# {category.title} - {category.blurb}", f"# {'-' * 74}"]
        for command in members:
            for name, dry in _dry_variants(command):
                summary = command.summary + (" (preview only)" if dry else "")
                lines += ["", f"# {summary}", f"{name}() {{"]
                lines += _posix_body(command, dry=dry)
                lines += ["}"]
    return lines


ZSH_ALIAS_GUARD = """
# An alias sharing a name with a wrapper below is fatal, not cosmetic: zsh
# expands aliases while *parsing*, so `remove-metadata() {` becomes
# `find ./ -type f …() {` and the parse error aborts the rest of this file -
# taking every wrapper after it with it.
#
# So stash any colliding alias, define the functions, then put it back.
# Clearing it outright would silently replace a command the user aliased on
# purpose; restoring it keeps their alias winning at the prompt, exactly as it
# did before che was installed. `che doctor` reports the collision, and
# `\\name` (backslash) reaches the wrapper without expanding the alias.
typeset -ga _che_stashed_aliases=()

_che_stash_aliases() {
  local name
  for name in "$@"; do
    if [[ -n ${aliases[$name]-} ]]; then
      _che_stashed_aliases+=("${name}=${aliases[$name]}")
      unalias -- "$name"
    fi
  done
}

_che_restore_aliases() {
  local entry
  for entry in "${_che_stashed_aliases[@]}"; do
    alias -- "$entry"
  done
  _che_stashed_aliases=()
}
"""

BASH_ALIAS_GUARD = """
# Same trap as zsh: with expand_aliases on (every interactive bash), an alias
# sharing a name with a wrapper below turns its definition into a syntax error
# and the rest of this file never loads. Stash, define, restore - so the user's
# alias keeps winning at the prompt and `\\name` reaches the wrapper.
_che_stashed_aliases=()

_che_stash_aliases() {
  local name
  for name in "$@"; do
    if alias "$name" >/dev/null 2>&1; then
      _che_stashed_aliases+=("$(alias "$name")")
      unalias "$name"
    fi
  done
}

_che_restore_aliases() {
  local entry
  for entry in "${_che_stashed_aliases[@]}"; do
    eval "$entry"
  done
  _che_stashed_aliases=()
}
"""


def _guarded_names() -> list[str]:
    """Every name the file defines, in the order the guard should clear them."""
    from commands import wrapper_names

    return ["che", *wrapper_names()]


def _stash_call() -> str:
    """`_che_stash_aliases` invocation, wrapped so the line stays readable."""
    lines: list[str] = []
    current = "_che_stash_aliases"
    for name in _guarded_names():
        candidate = f"{current} {name}"
        if len(candidate) > 76:
            lines.append(f"{current} \\")
            current = f"  {name}"
            continue
        current = candidate
    lines.append(current)
    return "\n".join(lines)


def _render_posix(shell: str) -> str:
    resolve_self = {
        "zsh": '  CHE_HOME="${${(%):-%x}:A:h:h}"',
        "bash": '  CHE_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"',
    }[shell]

    head = f"""{_banner()}
#
# Source this file (or let the `che install` block in your rc file do it):
#
#     . {"~/Developer/git/shell-functions/shell/che." + shell}
#
# Every wrapper is a shell function, so `type <name>` shows what it runs and
# `che doctor` can tell you when something it needs is missing.

# CHE_HOME is normally exported by the installed rc block. Fall back to this
# file's own location so a bare `source` of it also works.
if [ -z "${{CHE_HOME:-}}" ]; then
{resolve_self}
fi

CHE_BIN="${{CHE_HOME}}/bin"

# Any python3 on PATH by default. `che install` records the interpreter it
# verified (3.12+) in the rc block, which wins over this.
: "${{CHE_PYTHON:=python3}}"

# Legacy name from the hand-maintained wrappers, kept so an older snippet in
# ~/.zshrc that still refers to it keeps resolving.
SHELL_FUNCTIONS_BIN="${{CHE_BIN}}"

# Play the completion sound for a wrapper, then return the status it was given.
#
# playsound-N is defined outside this repo. Every wrapper used to call it
# unconditionally, which printed "command not found" on a machine that never
# had it; here a missing playsound is simply skipped. Set CHE_SOUNDS=0 to
# silence them all.
che_notify() {{
  if [ "${{CHE_SOUNDS:-1}}" = "1" ] && command -v "playsound-$1" >/dev/null 2>&1; then
    "playsound-$1" >/dev/null 2>&1
  fi
  return "${{2:-0}}"
}}

# The dispatcher. `che` with no arguments opens the interactive menu.
che() {{
  if [ "$#" -eq 0 ]; then
    "$CHE_PYTHON" "$CHE_BIN/che.py"
  else
    "$CHE_PYTHON" "$CHE_BIN/che.py" "$@"
    che_notify 7 $?
  fi
}}"""

    tail_by_shell = {
        "zsh": """
# Completions. compdef only exists once compinit has run; when it has not,
# skip quietly rather than erroring at shell start.
if whence -w compdef >/dev/null 2>&1 && [ -r "${CHE_HOME}/shell/completions/_che" ]; then
  . "${CHE_HOME}/shell/completions/_che"
fi""",
        "bash": """
# Completions, when this is bash and the completion builtin is available.
if [ -n "${BASH_VERSION:-}" ] && [ -r "${CHE_HOME}/shell/completions/che.bash" ]; then
  . "${CHE_HOME}/shell/completions/che.bash"
fi""",
    }

    guard = {"zsh": ZSH_ALIAS_GUARD, "bash": BASH_ALIAS_GUARD}[shell]

    return "\n".join(
        [
            head,
            guard.rstrip("\n"),
            "",
            _stash_call(),
            *_posix_wrappers(),
            "",
            "_che_restore_aliases",
            "",
            tail_by_shell[shell].strip("\n"),
            "",
        ]
    )


# ---------------------------------------------------------------------------
# fish
# ---------------------------------------------------------------------------


def _fish_quote(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _render_fish() -> str:
    lines = [
        _banner(),
        "",
        # No `cd` here: fish runs command substitution in the current process,
        # so `(cd ...; and pwd)` would move the user's shell as a side effect.
        "if not set -q CHE_HOME",
        "    set -l __che_dir (dirname (status --current-filename))/..",
        "    if type -q path",
        "        set -gx CHE_HOME (path resolve $__che_dir)",
        "    else",
        "        set -gx CHE_HOME $__che_dir",
        "    end",
        "    set -e __che_dir",
        "end",
        'set -g CHE_BIN "$CHE_HOME/bin"',
        "if not set -q CHE_PYTHON",
        "    set -gx CHE_PYTHON python3",
        "end",
        'set -gx SHELL_FUNCTIONS_BIN "$CHE_BIN"',
        "",
        "# Play a wrapper's completion sound, then return the status it was given.",
        "function che_notify --description 'che: completion sound'",
        "    set -l code 0",
        "    if set -q argv[2]",
        "        set code $argv[2]",
        "    end",
        '    if test "$CHE_SOUNDS" != "0"',
        '        if type -q "playsound-$argv[1]"',
        '            "playsound-$argv[1]" >/dev/null 2>&1',
        "        end",
        "    end",
        "    return $code",
        "end",
        "",
        "function che --description 'che: shell helpers dispatcher'",
        "    if test (count $argv) -eq 0",
        '        "$CHE_PYTHON" "$CHE_BIN/che.py"',
        "    else",
        '        "$CHE_PYTHON" "$CHE_BIN/che.py" $argv',
        "        che_notify 7 $status",
        "    end",
        "end",
    ]

    for category in CATEGORIES:
        members = [command for command in COMMANDS if command.category == category.key]
        if not members:
            continue
        lines += ["", f"# {'-' * 74}", f"# {category.title} - {category.blurb}", f"# {'-' * 74}"]
        for command in members:
            for name, dry in _dry_variants(command):
                env, args = command.invocation(dry=dry)
                summary = command.summary + (" (preview only)" if dry else "")
                lines += ["", f"function {name} --description {_fish_quote(summary)}"]

                if command.body:
                    # fish has no `$1`; the sh body's positional becomes $argv[1].
                    lines.append("    " + command.body.replace("$1", "$argv[1]"))
                else:
                    prefix = "".join(f"{key}={value} " for key, value in sorted(env.items()))
                    argv = "".join(f" {shlex.quote(arg)}" for arg in args)
                    runner = "env " + prefix if prefix else ""
                    lines.append(
                        f'    {runner}"$CHE_PYTHON" "$CHE_BIN/{command.script}"{argv} $argv'
                    )

                sound = command.dry_sound if dry else command.sound
                if sound is not None:
                    lines.append(f"    che_notify {sound} $status")
                lines.append("end")

    lines += [
        "",
        'if test -r "$CHE_HOME/shell/completions/che.fish"',
        '    source "$CHE_HOME/shell/completions/che.fish"',
        "end",
        "",
    ]
    return "\n".join(lines)


def wrappers(shell: str) -> str:
    """The generated wrapper file for ``shell``."""
    if shell == "fish":
        return _render_fish()
    if shell in ("zsh", "bash"):
        return _render_posix(shell)
    raise ValueError(f"unsupported shell: {shell}")


# ---------------------------------------------------------------------------
# Completions
# ---------------------------------------------------------------------------


def _all_completable() -> list[tuple[str, Command, bool]]:
    entries: list[tuple[str, Command, bool]] = []
    for command in (*COMMANDS, *BUILTINS):
        for name, dry in _dry_variants(command):
            entries.append((name, command, dry))
    return entries


def _zsh_completions() -> str:
    describe = []
    for name, command, dry in _all_completable():
        summary = command.summary + (" (preview)" if dry else "")
        describe.append(f"    {shlex.quote(f'{name}:{summary}')}")

    cases = []
    for name, command, _ in _all_completable():
        cases.append(f"    {name}) print -r -- {shlex.quote(' '.join(_flag_words(command)))} ;;")

    wrapper_names = " ".join(name for name, command, _ in _all_completable() if not command.builtin)

    return f"""#compdef che
{_banner()}

_che_flags_for() {{
  case "$1" in
{chr(10).join(cases)}
    *) print -r -- "--help" ;;
  esac
}}

_che_flag_complete() {{
  local cmd="$1" cur="${{words[CURRENT]}}"

  if [[ "$cur" == *=* ]]; then
    compset -P '*='
    _files
    return
  fi

  local -a flags
  flags=( ${{=$(_che_flags_for "$cmd")}} )
  compadd -S '' -- $flags
  _files
}}

_che() {{
  local -a subcommands
  subcommands=(
{chr(10).join(describe)}
  )

  if (( CURRENT == 2 )); then
    _describe -t commands 'che command' subcommands
    return
  fi

  _che_flag_complete "${{words[2]}}"
}}

_che_wrapper() {{
  _che_flag_complete "${{words[1]}}"
}}

compdef _che che
compdef _che_wrapper {wrapper_names}
"""


def _bash_completions() -> str:
    cases = []
    for name, command, _ in _all_completable():
        cases.append(f'    {name}) echo "{" ".join(_flag_words(command))}" ;;')

    names = " ".join(name for name, _, _ in _all_completable())
    wrapper_names = " ".join(name for name, command, _ in _all_completable() if not command.builtin)

    return f"""{_banner()}
# shellcheck shell=bash

_che_flags_for() {{
  case "$1" in
{chr(10).join(cases)}
    *) echo "--help" ;;
  esac
}}

# `mapfile` is bash 4+, and macOS still ships bash 3.2, so read the candidates
# a line at a time instead - which also keeps filenames with spaces intact.
_che_reply() {{
  local prefix="$1" line
  COMPREPLY=()
  while IFS= read -r line; do
    COMPREPLY+=( "$prefix$line" )
  done
}}

_che_complete_for() {{
  local cmd="$1" cur="$2" prefix value

  case "$cur" in
    *=*)
      prefix="${{cur%%=*}}="
      value="${{cur#*=}}"
      _che_reply "$prefix" < <(compgen -f -- "$value")
      ;;
    -*)
      _che_reply "" < <(compgen -W "$(_che_flags_for "$cmd")" -- "$cur")
      ;;
    *)
      _che_reply "" < <(compgen -f -- "$cur")
      ;;
  esac
}}

_che_complete() {{
  local cur="${{COMP_WORDS[COMP_CWORD]}}"

  if [ "$COMP_CWORD" -eq 1 ]; then
    _che_reply "" < <(compgen -W "{names}" -- "$cur")
    return
  fi

  _che_complete_for "${{COMP_WORDS[1]}}" "$cur"
}}

_che_complete_wrapper() {{
  _che_complete_for "${{COMP_WORDS[0]}}" "${{COMP_WORDS[COMP_CWORD]}}"
}}

complete -o nospace -F _che_complete che
complete -o nospace -F _che_complete_wrapper {wrapper_names}
"""


def _fish_completions() -> str:
    lines = [_banner(), ""]
    lines.append("complete -c che -f")
    for name, command, dry in _all_completable():
        summary = command.summary + (" (preview)" if dry else "")
        lines.append(
            f"complete -c che -n __fish_use_subcommand -a {name} -d {_fish_quote(summary)}"
        )

    lines.append("")
    for name, command, _ in _all_completable():
        for flag in command.flags:
            option = flag.removeprefix("--")
            takes_value = " -r" if flag in VALUE_FLAGS else ""
            paths = " -F" if flag in PATH_FLAGS else ""
            lines.append(
                f'complete -c che -n "__fish_seen_subcommand_from {name}" '
                f"-l {option}{takes_value}{paths}"
            )

    lines.append("")
    for name, command, _ in _all_completable():
        if command.builtin:
            continue
        for flag in command.flags:
            option = flag.removeprefix("--")
            takes_value = " -r" if flag in VALUE_FLAGS else ""
            paths = " -F" if flag in PATH_FLAGS else ""
            lines.append(f"complete -c {name} -l {option}{takes_value}{paths}")

    lines.append("")
    return "\n".join(lines)


def completions(shell: str) -> str:
    if shell == "zsh":
        return _zsh_completions()
    if shell == "bash":
        return _bash_completions()
    if shell == "fish":
        return _fish_completions()
    raise ValueError(f"unsupported shell: {shell}")


# ---------------------------------------------------------------------------
# The rc-file block, and the repo's own .zshrc compatibility shim
# ---------------------------------------------------------------------------


def rc_block(shell: str, *, home: Path, python: str, sounds: bool = True) -> str:
    """The machine-specific snippet ``che install`` writes into an rc file.

    Deliberately tiny: a path, an interpreter and a source line. Everything
    that can be generic lives in the committed ``shell/che.*`` file instead, so
    upgrading che never means rewriting the user's rc file.
    """
    wrapper = home / WRAPPER_FILES[shell]

    if shell == "fish":
        body = [
            BEGIN_MARKER,
            f"# Managed by `che install` (che {VERSION}). Edits here are overwritten.",
            f"set -gx CHE_HOME {_fish_quote(str(home))}",
            f"set -gx CHE_PYTHON {_fish_quote(python)}",
        ]
        if not sounds:
            body.append("set -gx CHE_SOUNDS 0")
        body += [
            f"if test -r {_fish_quote(str(wrapper))}",
            f"    source {_fish_quote(str(wrapper))}",
            "end",
            END_MARKER,
        ]
        return "\n".join(body) + "\n"

    body = [
        BEGIN_MARKER,
        f"# Managed by `che install` (che {VERSION}). Edits here are overwritten.",
        f"export CHE_HOME={shlex.quote(str(home))}",
        f"export CHE_PYTHON={shlex.quote(python)}",
    ]
    if not sounds:
        body.append("export CHE_SOUNDS=0")
    body += [
        f"[ -r {shlex.quote(str(wrapper))} ] && . {shlex.quote(str(wrapper))}",
        END_MARKER,
    ]
    return "\n".join(body) + "\n"


def legacy_zshrc() -> str:
    """The repo's own ``.zshrc``, kept as a one-line shim.

    It used to hold every wrapper by hand, and the documented workflow was to
    copy them into ``~/.zshrc`` - which meant the two drifted. Anyone still
    sourcing this file keeps working; the wrappers themselves now come from
    ``shell/che.zsh``.
    """
    return f"""{_banner()}
#
# The wrappers moved to shell/che.zsh and are generated from bin/commands.py.
# `che install` writes a block into ~/.zshrc that sources them; this file
# stays so that an existing `source .../shell-functions/.zshrc` keeps working.

CHE_HOME="${{CHE_HOME:-${{${{(%):-%x}}:A:h}}}}"
. "${{CHE_HOME}}/shell/che.zsh"
"""


def generated_files() -> dict[Path, str]:
    """Every generated path mapped to its expected contents, relative to the repo."""
    files: dict[Path, str] = {}
    for shell in SHELLS:
        files[WRAPPER_FILES[shell]] = wrappers(shell)
        files[COMPLETION_FILES[shell]] = completions(shell)
    files[Path(".zshrc")] = legacy_zshrc()
    return files


# ---------------------------------------------------------------------------
# README islands
#
# The parts of the README that restate the manifest - the command table, the
# preview twins, the menu keys, the external tools - are generated between
# markers and checked by `bun run ci`. Prose stays hand-written; facts that
# have a single source of truth are not retyped where they can go stale.
# ---------------------------------------------------------------------------

README = Path("README.md")


def _marker(name: str) -> tuple[str, str]:
    return f"<!-- che:{name} -->", f"<!-- /che:{name} -->"


def _commands_table() -> str:
    rows = ["| Command | Does | Preview |", "| --- | --- | --- |"]
    for category in CATEGORIES:
        members = [command for command in COMMANDS if command.category == category.key]
        if not members:
            continue
        rows.append(f"| **{category.title}** | *{category.blurb}* | |")
        for command in members:
            preview = f"`{command.dry_name}`" if command.has_dry_twin else ""
            if not preview and command.dry_run == "flag":
                preview = "`--dry-run`"
            if not preview and any(p.flag == "--dry-run" for p in command.prompts):
                preview = "`--dry-run`"
            if not preview and command.no_preview_reason:
                preview = "none"
            rows.append(f"| `{command.name}` | {command.summary} | {preview} |")
    return "\n".join(rows)


def _builtins_table() -> str:
    rows = ["| Command | Does |", "| --- | --- |"]
    for command in BUILTINS:
        rows.append(f"| `che {command.name}` | {command.summary} |")
    return "\n".join(rows)


def _keys_table() -> str:
    rows = ["| Key | Does |", "| --- | --- |"]
    for key, description in MENU_KEYS:
        rows.append(f"| `{key}` | {description} |")
    return "\n".join(rows)


def _tools_table() -> str:
    rows = ["| Tool | Needed by |", "| --- | --- |"]
    for binary, users in required_binaries().items():
        names = ", ".join(f"`{name}`" for name in users)
        rows.append(f"| `{binary}` | {names} |")

    extra = [command for command in COMMANDS if command.setup]
    for command in extra:
        rows.append(f"| (not a binary) | `{command.name}` {command.setup} |")
    return "\n".join(rows)


def readme_islands() -> dict[str, str]:
    return {
        "commands": _commands_table(),
        "builtins": _builtins_table(),
        "keys": _keys_table(),
        "tools": _tools_table(),
        "count": (
            f"{len(COMMANDS)} commands across {len({c.category for c in COMMANDS})} categories, "
            f"plus {len(BUILTINS)} built into `che` itself"
        ),
    }


def render_readme(current: str) -> str:
    """Replace every marked island in ``current`` with what the manifest says.

    Unmarked prose is left exactly as written. A marker that is missing from
    the README is reported rather than silently skipped, because a section that
    quietly stopped being checked is worse than one that was never checked.
    """
    updated = current
    for name, body in readme_islands().items():
        begin, end = _marker(name)
        if begin not in updated or end not in updated:
            raise ValueError(f"README.md is missing the {begin} … {end} markers")
        head, _, rest = updated.partition(begin)
        _, _, tail = rest.partition(end)
        updated = f"{head}{begin}\n{body}\n{end}{tail}"
    return updated
