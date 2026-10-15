"""Render the shell wrappers and completions from :mod:`commands`.

Everything under ``shell/`` is produced here, along with the README's
generated islands, and :func:`sync_generated` writes them to disk for both
``che install`` and ``bun run generate`` (which runs this module). Two rules
keep the generated files honest:

* **No machine-specific data.** These files are committed, so they must work
  from any clone path. The one machine-specific thing - where the repo lives
  and which ``python3`` to use - goes in the small block the installer writes
  into ``~/.zshrc``, not here. As a fallback the wrappers resolve their own
  location, so sourcing ``shell/che.zsh`` directly works with no block at all.
* **Deterministic.** A test re-renders and diffs against the files on disk,
  and ``bun run ci`` runs it, so generation may not depend on the environment
  it runs in.

Library module: no shebang, not executable. ``python3 bin/shellgen.py``
rewrites every generated file.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import art
from commands import (
    BUILTINS,
    COMMANDS,
    MENU_KEYS,
    REPO,
    VERSION,
    Command,
    Resolved,
    all_commands,
    grouped,
    required_binaries,
    variants,
    wrapper_names,
)
from utils import atomic_write_text

# The rc-file block is delimited by these. Anything between them belongs to
# `che install` and is rewritten wholesale on every install; anything outside
# is the user's and is never touched.
BEGIN_MARKER = "# >>> che shell functions >>>"
END_MARKER = "# <<< che shell functions <<<"


def _banner() -> str:
    return "\n".join(
        f"# {line}".rstrip()
        for line in (
            f"che {VERSION} - generated file, do not edit.",
            "",
            "Generated from bin/commands.py by `che install`.",
            "To change a wrapper, edit that manifest and run `che install` again.",
        )
    )


def _flag_words(command: Command) -> list[str]:
    """Completion words for one command: its flags plus the universal ones."""
    return [*command.flags, "--help"]


# ---------------------------------------------------------------------------
# Dialects: how each family of shells spells the same thing
# ---------------------------------------------------------------------------


class Dialect:
    """The syntax one family of shells writes the generated code in."""

    indent: str
    all_args: str  # every argument the function was called with
    status: str  # the last command's exit status
    env_runner: str  # what has to precede `NAME=value command`
    end: str  # closes a function

    @staticmethod
    def quote(text: str) -> str:
        raise NotImplementedError

    def header(self, name: str, summary: str) -> list[str]:
        """The lines that open a function definition."""
        raise NotImplementedError

    def file_head(self, shell: Shell) -> str:
        """Everything a wrapper file sets up before its first wrapper."""
        raise NotImplementedError

    def file_tail(self, shell: Shell) -> str:
        """Everything a wrapper file does after its last wrapper."""
        raise NotImplementedError

    def export(self, name: str, word: str) -> str:
        raise NotImplementedError

    def source_if_readable(self, path: Path) -> str:
        raise NotImplementedError

    def add_to_path(self, directory: Path) -> str:
        """Prepend ``directory`` to PATH unless it is already there."""
        raise NotImplementedError

    def wrapper(self, variant: Resolved) -> list[str]:
        """One wrapper function.

        DELIBERATE DIVERGENCE from the hand-written wrappers: every wrapper now
        forwards ``"$@"``. A few of them (clean-stale-branches, prune-worktrees)
        used to swallow their arguments, so ``clean-stale-branches --protect=x``
        silently ignored a flag the script documents.
        """
        assignments = "".join(
            f"{key}={self.quote(value)} " for key, value in sorted(variant.env.items())
        )
        runner = self.env_runner + assignments if assignments else ""
        argv = "".join(f" {self.quote(arg)}" for arg in variant.args)
        call = f'{runner}"$CHE_PYTHON" "$CHE_BIN/{variant.command.script}"{argv} {self.all_args}'

        lines = [*self.header(variant.name, variant.summary("preview only")), self.indent + call]
        if variant.sound is not None:
            # `$?` is expanded before che_notify runs, so the wrapper still returns
            # the script's exit status. The old wrappers returned playsound's.
            lines.append(f"{self.indent}che_notify {variant.sound} {self.status}")
        return [*lines, self.end]


class _Posix(Dialect):
    indent = "  "
    all_args = '"$@"'
    status = "$?"
    env_runner = ""
    end = "}"

    @staticmethod
    def quote(text: str) -> str:
        return shlex.quote(text)

    def header(self, name: str, summary: str) -> list[str]:
        return [f"# {summary}", f"{name}() {{"]

    def file_head(self, shell: Shell) -> str:
        return f"""{_banner()}
#
# Source this file (or let the `che install` block in your rc file do it):
#
#     . ~/Developer/git/che/{shell.wrapper_file}
#
# Every wrapper is a shell function, so `type <name>` shows what it runs and
# `che doctor` can tell you when something it needs is missing.

# CHE_HOME is normally exported by the installed rc block. Fall back to this
# file's own location so a bare `source` of it also works.
if [ -z "${{CHE_HOME:-}}" ]; then
  {shell.find_home}
fi
{POSIX_EXPORTS}{shell.alias_guard}
{_stash_call()}
{POSIX_FUNCTIONS.rstrip()}"""

    def file_tail(self, shell: Shell) -> str:
        return f"_che_restore_aliases\n\n{shell.load_completions}"

    def export(self, name: str, word: str) -> str:
        return f"export {name}={word}"

    def source_if_readable(self, path: Path) -> str:
        quoted = self.quote(str(path))
        return f"[ -r {quoted} ] && . {quoted}"

    def add_to_path(self, directory: Path) -> str:
        quoted = self.quote(str(directory))
        return f'case ":$PATH:" in *:{quoted}:*) ;; *) PATH={quoted}:"$PATH" ;; esac'


# The characters shlex.quote leaves unquoted.
_SAFE_WORD = re.compile(r"[\w@%+=:,./-]+", re.ASCII)


class _Fish(Dialect):
    indent = "    "
    all_args = "$argv"
    status = "$status"
    env_runner = "env "
    end = "end"

    @staticmethod
    def quote(text: str) -> str:
        # Bare when shlex would leave it bare too, so `--dry-run` reads the
        # same in every shell's wrapper.
        if _SAFE_WORD.fullmatch(text):
            return text
        return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"

    def header(self, name: str, summary: str) -> list[str]:
        return [f"function {name} --description {self.quote(summary)}"]

    def file_head(self, shell: Shell) -> str:
        return f"{_banner()}\n{FISH_PRELUDE}"

    def file_tail(self, shell: Shell) -> str:
        return shell.load_completions

    def export(self, name: str, word: str) -> str:
        return f"set -gx {name} {word}"

    def source_if_readable(self, path: Path) -> str:
        quoted = self.quote(str(path))
        return f"if test -r {quoted}\n    source {quoted}\nend"

    def add_to_path(self, directory: Path) -> str:
        quoted = self.quote(str(directory))
        return f"if not contains {quoted} $PATH\n    set -gx PATH {quoted} $PATH\nend"


POSIX = _Posix()
FISH = _Fish()


# ---------------------------------------------------------------------------
# The wrapper files
# ---------------------------------------------------------------------------

# What a POSIX wrapper file sets up once it has found CHE_HOME.
POSIX_EXPORTS = """
# Exported, not just set: every wrapper expands "$CHE_BIN", and a shell that
# replays the *functions* without re-reading this file - a `typeset -f` dump, an
# environment snapshot, any tool that rebuilds a shell from its exported
# environment - keeps the functions and drops a plain variable, leaving the
# wrappers to run "/che.py". CHE_HOME comes in exported by the rc block; this
# keeps everything derived from it exported too.
export CHE_BIN="${CHE_HOME}/bin"

# Any python3 on PATH by default. `che install` records the interpreter it
# verified (3.12+) in the rc block, which wins over this.
: "${CHE_PYTHON:=python3}"
export CHE_PYTHON

# Legacy name from the hand-maintained wrappers, kept so an older snippet in
# ~/.zshrc that still refers to it keeps resolving.
export SHELL_FUNCTIONS_BIN="${CHE_BIN}"
"""

# The two functions every wrapper relies on. They come after the alias guard:
# an alias named `che` would otherwise break `che() {` exactly the way the
# guard describes, and take the rest of the file with it.
POSIX_FUNCTIONS = """
# Play the completion sound for a wrapper, then return the status it was given.
#
# playsound-N is defined outside this repo. Every wrapper used to call it
# unconditionally, which printed "command not found" on a machine that never
# had it; here a missing playsound is simply skipped. Set CHE_SOUNDS=0 to
# silence them all.
che_notify() {
  if [ "${CHE_SOUNDS:-1}" != "0" ] && command -v "playsound-$1" >/dev/null 2>&1; then
    "playsound-$1" >/dev/null 2>&1
  fi
  return "${2:-0}"
}

# The dispatcher. `che` with no arguments opens the interactive menu.
che() {
  if [ "$#" -eq 0 ]; then
    "$CHE_PYTHON" "$CHE_BIN/che.py"
  else
    "$CHE_PYTHON" "$CHE_BIN/che.py" "$@"
    che_notify 7 $?
  fi
}
"""

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

# fish needs no alias guard, so its whole setup is one block. No `cd` in it:
# fish runs command substitution in the current process, so `(cd ...; and pwd)`
# would move the user's shell as a side effect.
FISH_PRELUDE = """
if not set -q CHE_HOME
    set -l __che_dir (dirname (status --current-filename))/..
    if type -q path
        set -gx CHE_HOME (path resolve $__che_dir)
    else
        set -gx CHE_HOME $__che_dir
    end
    set -e __che_dir
end
set -gx CHE_BIN "$CHE_HOME/bin"
if not set -q CHE_PYTHON
    set -gx CHE_PYTHON python3
end
set -gx SHELL_FUNCTIONS_BIN "$CHE_BIN"

# Play a wrapper's completion sound, then return the status it was given.
function che_notify --description 'che: completion sound'
    set -l code 0
    if set -q argv[2]
        set code $argv[2]
    end
    if test "$CHE_SOUNDS" != "0"
        if type -q "playsound-$argv[1]"
            "playsound-$argv[1]" >/dev/null 2>&1
        end
    end
    return $code
end

function che --description 'che: shell helpers dispatcher'
    if test (count $argv) -eq 0
        "$CHE_PYTHON" "$CHE_BIN/che.py"
    else
        "$CHE_PYTHON" "$CHE_BIN/che.py" $argv
        che_notify 7 $status
    end
end"""


def defined_names() -> list[str]:
    """Every function name a wrapper file defines: the sound helper, the
    dispatcher, then every wrapper."""
    return ["che_notify", "che", *wrapper_names()]


def _stash_call() -> str:
    """`_che_stash_aliases` for every name the file defines, wrapped to stay readable."""
    lines: list[str] = []
    current = "_che_stash_aliases"
    for name in defined_names():
        candidate = f"{current} {name}"
        if len(candidate) > 76:
            lines.append(f"{current} \\")
            current = f"  {name}"
            continue
        current = candidate
    lines.append(current)
    return "\n".join(lines)


def _wrapper_section(dialect: Dialect) -> list[str]:
    """Every wrapper, grouped under a banner per category."""
    lines: list[str] = []
    for category, members in grouped(COMMANDS):
        lines += ["", f"# {'-' * 74}", f"# {category.title} - {category.blurb}", f"# {'-' * 74}"]
        for variant in variants(members):
            lines += ["", *dialect.wrapper(variant)]
    return lines


def wrappers(shell: str) -> str:
    """The generated wrapper file for ``shell``."""
    spec = _shell(shell)
    dialect = spec.dialect
    return "\n".join(
        [dialect.file_head(spec), *_wrapper_section(dialect), "", dialect.file_tail(spec), ""]
    )


# ---------------------------------------------------------------------------
# Completions
# ---------------------------------------------------------------------------


def _zsh_completions() -> str:
    describe = [
        "    " + shlex.quote(f"{v.name}:{v.summary('preview')}") for v in variants(all_commands())
    ]
    cases = [
        f"    {v.name}) print -r -- {shlex.quote(' '.join(_flag_words(v.command)))} ;;"
        for v in variants(all_commands())
    ]

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
compdef _che_wrapper {" ".join(wrapper_names())}
"""


def _bash_completions() -> str:
    cases = [
        f'    {v.name}) echo "{" ".join(_flag_words(v.command))}" ;;'
        for v in variants(all_commands())
    ]
    names = " ".join(v.name for v in variants(all_commands()))

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
complete -o nospace -F _che_complete_wrapper {" ".join(wrapper_names())}
"""


def _fish_option(flag: str) -> str:
    """`-l name`, plus `-r` when the flag takes a value and `-F` when that value is a path."""
    spec = f"-l {flag.removeprefix('--').removesuffix('=')}"
    if flag.endswith("="):
        spec += " -r"
    if flag == "--path=":
        spec += " -F"
    return spec


def _fish_completions() -> str:
    lines = [_banner(), "", "complete -c che -f"]
    for v in variants(all_commands()):
        description = FISH.quote(v.summary("preview"))
        lines.append(f"complete -c che -n __fish_use_subcommand -a {v.name} -d {description}")

    lines.append("")
    for v in variants(all_commands()):
        for flag in v.command.flags:
            lines.append(
                f'complete -c che -n "__fish_seen_subcommand_from {v.name}" {_fish_option(flag)}'
            )

    lines.append("")
    for v in variants(COMMANDS):
        for flag in v.command.flags:
            lines.append(f"complete -c {v.name} {_fish_option(flag)}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shells
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Shell:
    """Everything that differs between the shells che generates files for."""

    name: str
    dialect: Dialect
    wrapper_file: Path  # relative to the repo root
    completion_file: Path
    completions: Callable[[], str]
    load_completions: str  # the end of the wrapper file
    # POSIX only: how a sourced file finds the repo, and the alias guard
    # around the definitions.
    find_home: str = ""
    alias_guard: str = ""


_SHELLS: dict[str, Shell] = {
    shell.name: shell
    for shell in (
        Shell(
            name="zsh",
            dialect=POSIX,
            wrapper_file=Path("shell/che.zsh"),
            completion_file=Path("shell/completions/_che"),
            completions=_zsh_completions,
            find_home='CHE_HOME="${${(%):-%x}:A:h:h}"',
            alias_guard=ZSH_ALIAS_GUARD,
            load_completions="""\
# Completions. compdef only exists once compinit has run; when it has not,
# skip quietly rather than erroring at shell start.
if whence -w compdef >/dev/null 2>&1 && [ -r "${CHE_HOME}/shell/completions/_che" ]; then
  . "${CHE_HOME}/shell/completions/_che"
fi""",
        ),
        Shell(
            name="bash",
            dialect=POSIX,
            wrapper_file=Path("shell/che.bash"),
            completion_file=Path("shell/completions/che.bash"),
            completions=_bash_completions,
            find_home='CHE_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"',
            alias_guard=BASH_ALIAS_GUARD,
            load_completions="""\
# Completions, when this is bash and the completion builtin is available.
if [ -n "${BASH_VERSION:-}" ] && [ -r "${CHE_HOME}/shell/completions/che.bash" ]; then
  . "${CHE_HOME}/shell/completions/che.bash"
fi""",
        ),
        Shell(
            name="fish",
            dialect=FISH,
            wrapper_file=Path("shell/che.fish"),
            completion_file=Path("shell/completions/che.fish"),
            completions=_fish_completions,
            load_completions="""\
if test -r "$CHE_HOME/shell/completions/che.fish"
    source "$CHE_HOME/shell/completions/che.fish"
end""",
        ),
    )
}

# The shell flavors there are generated files for: `machine.ShellSpec.flavor`.
FLAVORS = tuple(_SHELLS)


def _shell(name: str) -> Shell:
    try:
        return _SHELLS[name]
    except KeyError:
        raise ValueError(f"unsupported shell: {name}") from None


def completions(shell: str) -> str:
    return _shell(shell).completions()


# ---------------------------------------------------------------------------
# The rc-file block, and the repo's own .zshrc compatibility shim
# ---------------------------------------------------------------------------


def rc_block(
    shell: str, *, home: Path, python: str, sounds: bool = True, path_dir: Path | None = None
) -> str:
    """The machine-specific snippet ``che install`` writes into an rc file.

    Deliberately tiny: a path, an interpreter and a source line, plus the line
    that puts ``path_dir`` (where the ``che`` shim lives) on PATH when given.
    Everything that can be generic lives in the committed ``shell/che.*`` file
    instead, so upgrading che never means rewriting the user's rc file.
    """
    spec = _shell(shell)
    dialect = spec.dialect
    lines = [
        BEGIN_MARKER,
        f"# Managed by `che install` (che {VERSION}). Edits here are overwritten.",
        dialect.export("CHE_HOME", dialect.quote(str(home))),
        dialect.export("CHE_PYTHON", dialect.quote(python)),
    ]
    if not sounds:
        lines.append(dialect.export("CHE_SOUNDS", "0"))
    lines.append(dialect.source_if_readable(home / spec.wrapper_file))
    if path_dir is not None:
        lines.append(dialect.add_to_path(path_dir))
    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def legacy_zshrc() -> str:
    """The repo's own ``.zshrc``, kept as a one-line shim.

    It used to hold every wrapper by hand, and the documented workflow was to
    copy them into ``~/.zshrc`` - which meant the two drifted. Anyone still
    sourcing this file keeps working; the wrappers themselves now come from
    ``shell/che.zsh``.
    """
    return (
        _banner()
        + """
#
# The wrappers moved to shell/che.zsh and are generated from bin/commands.py.
# `che install` writes a block into ~/.zshrc that sources them; this file
# stays so that an existing `source .../shell-functions/.zshrc` keeps working.

CHE_HOME="${CHE_HOME:-${${(%):-%x}:A:h}}"
. "${CHE_HOME}/shell/che.zsh"
"""
    )


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


def _md_row(*cells: str) -> str:
    return f"| {' | '.join(cells)} |"


def _md_table(headers: Sequence[str], rows: Iterable[str]) -> str:
    return "\n".join([_md_row(*headers), _md_row(*["---"] * len(headers)), *rows])


def _commands_table() -> str:
    rows = []
    for category, members in grouped(COMMANDS):
        rows.append(f"| **{category.title}** | *{category.blurb}* | |")
        for command in members:
            preview = command.preview
            cell = f"`{preview}`" if preview else ("none" if command.no_preview_reason else "")
            rows.append(_md_row(f"`{command.name}`", command.summary, cell))
    return _md_table(("Command", "Does", "Preview"), rows)


def _builtins_table() -> str:
    rows = (_md_row(f"`che {command.name}`", command.summary) for command in BUILTINS)
    return _md_table(("Command", "Does"), rows)


def _keys_table() -> str:
    rows = (_md_row(f"`{key}`", description) for key, description in MENU_KEYS)
    return _md_table(("Key", "Does"), rows)


def _tools_table() -> str:
    rows = [
        _md_row(f"`{binary}`", ", ".join(f"`{name}`" for name in users))
        for binary, users in required_binaries().items()
    ]
    rows += [
        _md_row("(not a binary)", f"`{command.name}` {command.setup}")
        for command in COMMANDS
        if command.setup
    ]
    return _md_table(("Tool", "Needed by"), rows)


def _banner_island() -> str:
    """The face beside the wordmark: the terminal banner without its colour,
    indent and subtitle."""
    rows = art.compose(art.FACE_LINES, art.LOGO_LINES)
    return "```text\n" + "\n".join(rows) + "\n```"


def readme_islands() -> dict[str, str]:
    return {
        "banner": _banner_island(),
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


# ---------------------------------------------------------------------------
# Writing it all out
# ---------------------------------------------------------------------------


def expected_files() -> dict[Path, str]:
    """Every generated path, relative to the repo, mapped to the contents the
    manifest implies.

    ``shell/`` is generated whole. The README is generated in place: only the
    marked islands are replaced, so its prose survives.
    """
    expected: dict[Path, str] = {}
    for spec in _SHELLS.values():
        expected[spec.wrapper_file] = wrappers(spec.name)
        expected[spec.completion_file] = spec.completions()
    expected[Path(".zshrc")] = legacy_zshrc()

    readme = REPO / README
    if readme.exists():
        expected[README] = render_readme(readme.read_text(encoding="utf-8"))

    return expected


def sync_generated(*, dry_run: bool) -> list[Path]:
    """Bring the generated files up to date; returns the ones that were stale.

    With ``dry_run`` nothing is written, which makes it the check CI runs.
    Raises ``ValueError`` when the README has lost one of its markers.

    Each file is replaced atomically: ``che install`` rewrites ``shell/`` in
    place, and a shell starting at that moment must not source half a file.
    """
    changed = []
    for relative, contents in expected_files().items():
        target = REPO / relative
        if target.exists() and target.read_text(encoding="utf-8") == contents:
            continue
        changed.append(relative)
        if not dry_run:
            atomic_write_text(target, contents)
    return changed


if __name__ == "__main__":
    try:
        written = sync_generated(dry_run=False)
    except ValueError as exc:
        raise SystemExit(f"❌ {exc}") from None
    for path in written:
        print(f"wrote {path}")
    print(f"{len(written)} generated file(s) updated")
