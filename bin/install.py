#!/usr/bin/env python3
"""Install the ``che`` wrappers into the shells this machine actually has.

Run it directly on a fresh machine::

    python3 bin/install.py            # first-run wizard
    python3 bin/install.py --yes      # same, no questions asked

or, once the wrappers exist, through the dispatcher: ``che install``,
``che doctor``, ``che update``, ``che uninstall``.

What "installed" means here is deliberately small. Three things go into the
user's rc file - where the repo is, which python to use, and a line that
sources the generated wrapper file - between two markers this script owns.
Everything else (the wrappers themselves, the completions) lives in the repo
and is regenerated from ``bin/commands.py``, so upgrading never rewrites the
user's dotfiles.

Unlike the destructive scripts under ``bin/<category>/``, this one does NOT
default to dry-run: it is the entry point that creates the wrappers, so
defaulting to "change nothing" would leave a first-time user with nothing
installed and no obvious reason why. ``--dry-run`` is still there, and every
file it touches is backed up first.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# install.py sits at the bin/ root next to the libraries it imports, so this is
# `parent`, where the scripts under bin/<category>/ use `parent.parent`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import shellgen
from commands import REPO, VERSION, all_commands, required_binaries
from tui import choose, confirm, is_interactive, palette
from utils import add_bool_flag, build_parser, info, note, run, success, warning

__version__ = "1.0.0"

MIN_PYTHON = (3, 12)

# Binary -> how to get it. Anything absent from here is either part of macOS or
# has no obvious one-liner, and doctor says so rather than inventing a command.
INSTALL_HINTS: dict[str, str] = {
    "ffmpeg": "brew install ffmpeg",
    "ffprobe": "brew install ffmpeg",
    "mpv": "brew install mpv",
    "exiftool": "brew install exiftool",
    "gh": "brew install gh",
    "btop": "brew install btop",
    "git": "brew install git",
    "brew": 'bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
}

# Binaries that ship with macOS: never suggest installing them, just report.
SYSTEM_BINARIES = frozenset({"diskutil", "osascript", "sfltool"})

BREW_FORMULA = {
    "ffprobe": "ffmpeg",
    "ffmpeg": "ffmpeg",
    "mpv": "mpv",
    "exiftool": "exiftool",
    "gh": "gh",
    "btop": "btop",
    "git": "git",
}


# ---------------------------------------------------------------------------
# Locations
#
# Every path is resolved from the environment at call time, never at import
# time, so the tests can point HOME at a temporary directory.
# ---------------------------------------------------------------------------


def home() -> Path:
    return Path(os.environ.get("HOME", str(Path.home())))


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(home() / ".config")
    return Path(base) / "che"


def config_file() -> Path:
    return config_dir() / "config.json"


def backup_dir() -> Path:
    return config_dir() / "backups"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(home() / ".local" / "state")
    return Path(base) / "che"


def shim_path() -> Path:
    return home() / ".local" / "bin" / "che"


# ---------------------------------------------------------------------------
# Shells
# ---------------------------------------------------------------------------


@dataclass
class ShellTarget:
    """One shell che can install into, and the rc files it would touch."""

    name: str
    rc_files: list[Path] = field(default_factory=list)
    binary: str | None = None
    is_login_shell: bool = False

    @property
    def installed(self) -> bool:
        """Whether the shell itself exists on this machine."""
        return self.binary is not None

    @property
    def has_rc(self) -> bool:
        return any(path.exists() for path in self.rc_files)


def login_shell() -> str:
    return Path(os.environ.get("SHELL", "")).name


def _bash_rc_files() -> list[Path]:
    """Which bash startup files to write.

    macOS Terminal and iTerm start bash as a *login* shell, which reads
    ``.bash_profile`` and never ``.bashrc``; most Linux terminals do the
    opposite. Writing to whichever already exist (and to ``.bashrc`` when
    neither does) covers both without the usual "why isn't my alias there"
    hunt. The block is idempotent, so a ``.bash_profile`` that sources
    ``.bashrc`` just defines the same functions twice, harmlessly.
    """
    candidates = [home() / ".bashrc", home() / ".bash_profile"]
    existing = [path for path in candidates if path.exists()]
    return existing or [home() / ".bashrc"]


def _zsh_rc_files() -> list[Path]:
    zdotdir = os.environ.get("ZDOTDIR")
    base = Path(zdotdir) if zdotdir else home()
    return [base / ".zshrc"]


def _fish_rc_files() -> list[Path]:
    base = os.environ.get("XDG_CONFIG_HOME") or str(home() / ".config")
    return [Path(base) / "fish" / "config.fish"]


def _sh_rc_files() -> list[Path]:
    return [home() / ".profile"]


RC_RESOLVERS = {
    "zsh": _zsh_rc_files,
    "bash": _bash_rc_files,
    "fish": _fish_rc_files,
    "sh": _sh_rc_files,
}

# `sh` reuses the bash wrapper file: it is plain POSIX shell apart from the
# completion tail, which is guarded by a $BASH_VERSION test.
WRAPPER_FOR_SHELL = {"zsh": "zsh", "bash": "bash", "fish": "fish", "sh": "bash"}


def detect_shells() -> list[ShellTarget]:
    """Every supported shell, whether or not it is present on this machine."""
    current = login_shell()
    targets = []
    for name, resolver in RC_RESOLVERS.items():
        targets.append(
            ShellTarget(
                name=name,
                rc_files=resolver(),
                binary=shutil.which(name),
                is_login_shell=(name == current),
            )
        )
    return targets


def default_shell_selection(targets: list[ShellTarget]) -> list[str]:
    """What to install into when the user does not say.

    The login shell always, plus any other shell that is both installed and
    already has an rc file - those are shells the user demonstrably uses.
    ``sh``/``.profile`` is opt-in only; writing there affects every POSIX shell
    on the machine and is rarely what someone means.
    """
    chosen = [target.name for target in targets if target.is_login_shell and target.name != "sh"]
    for target in targets:
        if target.name in ("sh", *chosen):
            continue
        if target.installed and target.has_rc:
            chosen.append(target.name)
    return chosen or ["zsh"]


# ---------------------------------------------------------------------------
# Python interpreter
# ---------------------------------------------------------------------------


def python_version(executable: str) -> tuple[int, ...] | None:
    """Version of another interpreter, or None if it cannot be asked."""
    if executable == sys.executable:
        return sys.version_info[:3]
    try:
        output = run(
            [executable, "-c", "import sys; print('.'.join(str(p) for p in sys.version_info[:3]))"],
            capture=True,
            check=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return tuple(int(part) for part in output.strip().split("."))
    except ValueError:
        return None


def find_python() -> tuple[str, tuple[int, ...] | None]:
    """Pick the interpreter the wrappers should use.

    The interpreter running this script wins when it is new enough - it is the
    one the user just proved works. Otherwise fall back to the newest suitable
    ``python3.X`` on PATH. macOS matters here: ``/usr/bin/python3`` is whatever
    the Command Line Tools shipped, often years behind the Homebrew python that
    is also installed.
    """
    if sys.version_info[:2] >= MIN_PYTHON:
        return sys.executable, sys.version_info[:3]

    candidates = ["python3.14", "python3.13", "python3.12", "python3"]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if not resolved:
            continue
        version = python_version(resolved)
        if version and version[:2] >= MIN_PYTHON:
            return resolved, version

    return sys.executable, sys.version_info[:3]


# ---------------------------------------------------------------------------
# rc-file surgery
# ---------------------------------------------------------------------------

BEGIN = shellgen.BEGIN_MARKER
END = shellgen.END_MARKER


def read_rc(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def find_block(text: str) -> tuple[int, int] | None:
    """Character span of the managed block, or None when it is not there."""
    start = text.find(BEGIN)
    if start < 0:
        return None
    end = text.find(END, start)
    if end < 0:
        # A truncated block (someone deleted the end marker): treat everything
        # from the start marker to end of file as ours rather than appending a
        # second copy that would never be found again.
        return start, len(text)
    return start, end + len(END)


def backup_file(path: Path, *, dry_run: bool = False) -> Path | None:
    """Copy ``path`` into the backup directory before it is edited."""
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir() / f"{path.name.lstrip('.')}.{stamp}.bak"
    if dry_run:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


def apply_block(path: Path, block: str, *, dry_run: bool = False) -> str:
    """Insert or replace the managed block in ``path``.

    Returns one of ``created``, ``updated``, ``unchanged``. The block goes at
    the *end* of the file on a fresh install so that its definitions win over
    anything defined earlier, and stays exactly where it is on an update so a
    user who moved it keeps their placement.
    """
    original = read_rc(path)
    span = find_block(original)

    if span is None:
        separator = "" if not original or original.endswith("\n\n") else "\n"
        if original and not original.endswith("\n"):
            separator = "\n\n"
        updated = f"{original}{separator}{block}"
        action = "created"
    else:
        start, end = span
        if original[start:end].rstrip() == block.rstrip():
            return "unchanged"
        updated = original[:start] + block.rstrip("\n") + original[end:]
        action = "updated"

    if dry_run:
        return action

    backup_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return action


def remove_block(path: Path, *, dry_run: bool = False) -> bool:
    """Take the managed block back out. Returns whether anything changed."""
    original = read_rc(path)
    span = find_block(original)
    if span is None:
        return False
    if dry_run:
        return True

    start, end = span
    updated = original[:start].rstrip("\n") + "\n" + original[end:].lstrip("\n")
    backup_file(path)
    path.write_text(updated, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Legacy hand-written wrappers
# ---------------------------------------------------------------------------

LEGACY_VARIABLE = "SHELL_FUNCTIONS_BIN"

_ASSIGNMENT = re.compile(rf"^(?:export\s+)?{LEGACY_VARIABLE}=")
_FUNCTION_HEAD = re.compile(r"^(?:function\s+)?([A-Za-z0-9_.-]+)\s*\(\)\s*\{$")


@dataclass(frozen=True)
class LegacyBlock:
    """One hand-written wrapper (or the helper behind it) found in an rc file."""

    start: int
    end: int
    name: str
    body: str


def find_legacy(text: str) -> list[str]:
    """Names of hand-written wrappers in ``text`` that che now generates.

    Before the installer existed, the documented workflow was to copy the
    repo's ``.zshrc`` wrappers into ``~/.zshrc`` by hand, so most machines have
    a few dozen of them sitting there. They are harmless - the managed block is
    appended after, so its definitions win - but they go stale, which is why
    doctor reports them and ``--replace-legacy`` removes them.
    """
    spans, _ = _legacy_spans(text)
    return [name for _, _, name in spans if name]


def _function_blocks(lines: list[str], managed: range) -> list[LegacyBlock]:
    """Every complete ``name() { … }`` outside the managed block."""
    blocks: list[LegacyBlock] = []
    index = 0

    while index < len(lines):
        if index in managed:
            index += 1
            continue

        head = _FUNCTION_HEAD.match(lines[index].strip())
        if not head:
            index += 1
            continue

        depth = 1
        cursor = index + 1
        body: list[str] = []
        while cursor < len(lines) and depth > 0:
            depth += lines[cursor].count("{") - lines[cursor].count("}")
            body.append(lines[cursor])
            cursor += 1

        if depth == 0:
            blocks.append(LegacyBlock(index, cursor, head.group(1), "\n".join(body)))
            index = cursor
            continue

        index += 1

    return blocks


def _legacy_spans(text: str) -> tuple[list[tuple[int, int, str]], set[str]]:
    """Line spans holding legacy wrappers, plus the helper names among them.

    Seeded with everything that mentions ``SHELL_FUNCTIONS_BIN`` directly, then
    grown: a function that calls a legacy *helper* is legacy too. That second
    step is what handles a table-driven rc file, where the wrappers are built
    by an ``_sf`` helper that itself only calls ``_sf_run``.

    Growth deliberately stops at helpers. A function of the user's own that
    happens to call ``sync-all-branches`` is their automation, not a wrapper,
    and must survive untouched.
    """
    lines = text.splitlines()
    managed = _managed_line_range(lines)
    blocks = _function_blocks(lines, managed)

    from commands import wrapper_names

    generated = set(wrapper_names())

    marked = {block for block in blocks if LEGACY_VARIABLE in block.body}
    helpers = {block.name for block in marked if block.name not in generated}

    while True:
        grown = {
            block
            for block in blocks
            if block not in marked and any(helper in block.body for helper in helpers)
        }
        if not grown:
            break
        marked |= grown
        helpers |= {block.name for block in grown if block.name not in generated}

    spans = [(_extend_upwards(lines, block.start), block.end, block.name) for block in marked]
    spans += [
        (_extend_upwards(lines, index), index + 1, "")
        for index, line in enumerate(lines)
        if index not in managed and _ASSIGNMENT.match(line.strip())
    ]
    return sorted(spans), helpers


def _extend_upwards(lines: list[str], start: int) -> int:
    """Pull the comment block that documents a wrapper into its span.

    Every wrapper in the old ``.zshrc`` had a banner or a sentence above it.
    Removing the function but leaving its comment behind produces a file full
    of headings with nothing under them, so the span starts at the first line
    of the attached comment instead. The walk stops at the first line that is
    neither a comment nor the single blank line between a banner and what it
    introduces, so a comment belonging to code that stays is never taken.
    """
    cursor = start
    if cursor > 0 and not lines[cursor - 1].strip():
        cursor -= 1
    while cursor > 0 and lines[cursor - 1].lstrip().startswith("#"):
        cursor -= 1
    return cursor if lines[cursor].lstrip().startswith("#") else start


def find_shadowing(text: str) -> list[tuple[str, str]]:
    """Names in ``text`` that would win over a generated wrapper.

    Two ways that happens, both silent: an alias of the same name (in zsh and
    bash an alias is resolved before a function, so `alias remove-metadata=...`
    makes the wrapper dead code), and a function redefined *after* the managed
    block, since the last definition wins. Definitions before the block are
    fine, so they are not reported.
    """
    from commands import wrapper_names

    names = set(wrapper_names())
    span = find_block(text)
    block_end = span[1] if span else len(text)

    alias_pattern = re.compile(r"^alias\s+([A-Za-z0-9_.-]+)=")
    function_pattern = re.compile(r"^(?:function\s+)?([A-Za-z0-9_.-]+)\s*(?:\(\))?\s*\{")

    found: list[tuple[str, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        start_of_line, offset = offset, offset + len(line)

        alias = alias_pattern.match(stripped)
        if alias and alias.group(1) in names:
            found.append((alias.group(1), "alias"))
            continue

        if start_of_line <= block_end:
            # Defined before or inside our block: ours is sourced later and
            # wins, so there is nothing to report.
            continue

        definition = function_pattern.match(stripped)
        if definition and definition.group(1) in names:
            found.append((definition.group(1), "redefined after the block"))

    return found


def _managed_line_range(lines: list[str]) -> range:
    """Line indices covered by the managed block, so stripping never enters it."""
    begin = end = None
    for index, line in enumerate(lines):
        if line.startswith(BEGIN):
            begin = index
        elif line.startswith(END):
            end = index
    if begin is None:
        return range(0, 0)
    return range(begin, (end if end is not None else len(lines) - 1) + 1)


def _consecutive_groups(indices: list[int]) -> list[list[int]]:
    groups: list[list[int]] = []
    for index in sorted(indices):
        if groups and index == groups[-1][-1] + 1:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


def strip_legacy(path: Path, *, dry_run: bool = False) -> list[str]:
    """Remove legacy wrappers from ``path``; returns the names removed.

    Two passes. The first drops the ``SHELL_FUNCTIONS_BIN`` assignment, every
    function that used it, and the helpers those functions were built from,
    along with the comment documenting each. The second drops the lines that
    *call* a removed helper - which is what makes a table-driven ``~/.zshrc``
    safe to clean: removing an ``_sf`` helper while leaving its forty
    ``_sf <name> …`` lines behind would turn every new shell into forty
    "command not found" errors.

    Calls to removed *wrappers* are never touched, only calls to helpers. A
    line of the user's own that runs ``mount-all-drives`` at login is theirs.
    """
    original = read_rc(path)
    spans, helpers = _legacy_spans(original)
    if not spans:
        return []

    removed = [name for _, _, name in spans if name]
    lines = original.splitlines()
    managed = _managed_line_range(lines)

    drop: set[int] = set()
    for span_start, span_end, _ in spans:
        drop.update(range(span_start, span_end))

    callers = [
        index
        for index, line in enumerate(lines)
        if index not in drop and index not in managed and line.strip().split(" ")[0] in helpers
    ]
    for group in _consecutive_groups(callers):
        drop.update(range(_extend_upwards(lines, group[0]), group[-1] + 1))

    if dry_run:
        return removed

    kept = [line for index, line in enumerate(lines) if index not in drop]

    # Collapse the runs of blank lines the removal leaves behind, so the rc
    # file does not end up with a hole in it.
    tidied: list[str] = []
    for line in kept:
        if not line.strip() and tidied and not tidied[-1].strip():
            continue
        tidied.append(line)

    backup_file(path)
    path.write_text("\n".join(tidied).rstrip("\n") + "\n", encoding="utf-8")
    return removed


# ---------------------------------------------------------------------------
# Generated files and the PATH shim
# ---------------------------------------------------------------------------


def _expected_files() -> dict[Path, str]:
    """Every generated path mapped to the contents the manifest implies.

    ``shell/`` is generated whole. The README is generated in place: only the
    marked islands are replaced, so its prose survives.
    """
    expected = dict(shellgen.generated_files())

    readme = REPO / shellgen.README
    if readme.exists():
        expected[shellgen.README] = shellgen.render_readme(readme.read_text(encoding="utf-8"))

    return expected


def write_generated(*, dry_run: bool = False) -> list[Path]:
    """Refresh the generated files; returns the ones that changed."""
    changed = []
    for relative, contents in _expected_files().items():
        target = REPO / relative
        if target.exists() and target.read_text(encoding="utf-8") == contents:
            continue
        changed.append(relative)
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
    return changed


def check_generated() -> list[Path]:
    """Generated files that differ from what the manifest would produce."""
    stale = []
    for relative, contents in _expected_files().items():
        target = REPO / relative
        if not target.exists() or target.read_text(encoding="utf-8") != contents:
            stale.append(relative)
    return stale


def install_shim(python: str, *, dry_run: bool = False) -> str:
    """Put a ``che`` executable on PATH, for use outside an interactive shell.

    The shell function is what a human types; this shim is what a cron job, a
    Makefile or another script can call, none of which source an rc file.
    """
    target = shim_path()
    script = (
        "#!/bin/sh\n"
        f"# Generated by `che install` (che {VERSION}). Do not edit.\n"
        f'exec {json.dumps(python)} {json.dumps(str(REPO / "bin" / "che.py"))} "$@"\n'
    )

    if target.exists() and target.read_text(encoding="utf-8") == script:
        return "unchanged"
    if dry_run:
        return "installed"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(script, encoding="utf-8")
    target.chmod(0o755)
    return "installed"


def shim_on_path() -> bool:
    entries = os.environ.get("PATH", "").split(os.pathsep)
    return str(shim_path().parent) in entries


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config() -> dict:
    try:
        return json.loads(config_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(config: dict, *, dry_run: bool = False) -> None:
    if dry_run:
        return
    config_dir().mkdir(parents=True, exist_ok=True)
    config_file().write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def binary_status() -> dict[str, dict]:
    """Every external binary the commands need, and whether it is present."""
    status = {}
    for binary, users in required_binaries().items():
        resolved = shutil.which(binary)
        status[binary] = {
            "path": resolved,
            "present": bool(resolved),
            "commands": list(users),
            "hint": INSTALL_HINTS.get(binary, ""),
            "system": binary in SYSTEM_BINARIES,
        }
    return status


def install_missing_binaries(names: list[str], *, dry_run: bool = False) -> bool:
    """Install missing tools with Homebrew. Returns whether it ran cleanly."""
    formulae = sorted({BREW_FORMULA[name] for name in names if name in BREW_FORMULA})
    if not formulae:
        return True
    if not shutil.which("brew"):
        warning("❌ Homebrew is not installed; install the tools yourself:")
        for name in names:
            note(f"   {INSTALL_HINTS.get(name, name)}")
        return False

    info(f"Installing: {' '.join(formulae)}")
    if dry_run:
        return True
    result = run(["brew", "install", *formulae], check=False)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


@dataclass
class InstallPlan:
    shells: list[str]
    python: str
    sounds: bool = True
    completions: bool = True
    path_shim: bool = True
    replace_legacy: bool = False
    dry_run: bool = False


@dataclass
class InstallResult:
    rc_actions: list[tuple[Path, str]] = field(default_factory=list)
    generated: list[Path] = field(default_factory=list)
    legacy_removed: dict[str, list[str]] = field(default_factory=dict)
    shim: str = "skipped"


def perform_install(plan: InstallPlan) -> InstallResult:
    """Do the install described by ``plan``. No prompting happens here."""
    result = InstallResult()
    result.generated = write_generated(dry_run=plan.dry_run)

    targets = {target.name: target for target in detect_shells()}

    for shell in plan.shells:
        target = targets.get(shell)
        if target is None:
            warning(f"❌ Unknown shell: {shell}")
            continue

        block = shellgen.rc_block(
            WRAPPER_FOR_SHELL[shell],
            home=REPO,
            python=plan.python,
            sounds=plan.sounds,
        )
        if plan.path_shim and shell != "fish":
            block = _with_path_line(block)
        elif plan.path_shim and shell == "fish":
            block = _with_fish_path_line(block)

        for rc_file in target.rc_files:
            if plan.replace_legacy:
                removed = strip_legacy(rc_file, dry_run=plan.dry_run)
                if removed:
                    result.legacy_removed[str(rc_file)] = removed
            action = apply_block(rc_file, block, dry_run=plan.dry_run)
            result.rc_actions.append((rc_file, action))

    if plan.path_shim:
        result.shim = install_shim(plan.python, dry_run=plan.dry_run)

    save_config(
        {
            "version": VERSION,
            "home": str(REPO),
            "python": plan.python,
            "shells": plan.shells,
            "rc_files": [str(path) for path, _ in result.rc_actions],
            "sounds": plan.sounds,
            "completions": plan.completions,
            "path_shim": plan.path_shim,
            "installed_at": datetime.now().isoformat(timespec="seconds"),
        },
        dry_run=plan.dry_run,
    )
    return result


def _with_path_line(block: str) -> str:
    """Add ``~/.local/bin`` to PATH inside the managed block, idempotently."""
    directory = str(shim_path().parent)
    line = f'case ":$PATH:" in *":{directory}:"*) ;; *) PATH="{directory}:$PATH" ;; esac'
    return block.replace(END, f"{line}\n{END}")


def _with_fish_path_line(block: str) -> str:
    directory = str(shim_path().parent)
    line = f'if not contains "{directory}" $PATH\n    set -gx PATH "{directory}" $PATH\nend'
    return block.replace(shellgen.END_MARKER, f"{line}\n{shellgen.END_MARKER}")


# ---------------------------------------------------------------------------
# The first-run wizard
# ---------------------------------------------------------------------------

LOGO = r"""
   ██████╗██╗  ██╗███████╗
  ██╔════╝██║  ██║██╔════╝
  ██║     ███████║█████╗
  ██║     ██╔══██║██╔══╝
  ╚██████╗██║  ██║███████╗
   ╚═════╝╚═╝  ╚═╝╚══════╝
"""


def print_logo(subtitle: str = "") -> None:
    colors = palette()
    for line in LOGO.strip("\n").splitlines():
        print(f"{colors.bright_magenta}{line}{colors.reset}")
    if subtitle:
        print(f"  {colors.grey}{subtitle}{colors.reset}")
    print()


def wizard(*, dry_run: bool = False) -> int:
    """Walk a first-time user through the whole setup."""
    colors = palette()
    print_logo(f"shell helpers, v{VERSION} - first-run setup")

    python, version = find_python()
    version_text = ".".join(str(part) for part in (version or ()))
    if not version or version[:2] < MIN_PYTHON:
        warning(
            f"❌ Python {'.'.join(str(p) for p in MIN_PYTHON)}+ is required (found {version_text})."
        )
        note("   Install one with `brew install python@3.13`, then run this again.")
        return 1

    print(
        f"  {colors.green}✓{colors.reset} python {version_text}  {colors.grey}{python}{colors.reset}"
    )
    print(f"  {colors.green}✓{colors.reset} repo    {colors.grey}{REPO}{colors.reset}")
    print(f"  {colors.green}✓{colors.reset} {len(all_commands())} commands ready to wrap")
    print()

    targets = detect_shells()
    selectable = [target for target in targets if target.installed or target.has_rc]
    if not selectable:
        selectable = [target for target in targets if target.name == "zsh"]

    preselected = default_shell_selection(targets)
    options = []
    for target in selectable:
        rc_names = ", ".join(str(path).replace(str(home()), "~") for path in target.rc_files)
        label = target.name + ("  (your login shell)" if target.is_login_shell else "")
        options.append((label, rc_names))

    picked = choose(
        "Which shells should che install into?",
        options,
        selected=[index for index, target in enumerate(selectable) if target.name in preselected],
    )
    if not picked:
        warning("Nothing selected - install cancelled.")
        return 1
    shells = [selectable[index].name for index in picked]

    print()
    path_shim = confirm(
        f"Add a `che` command to {str(shim_path()).replace(str(home()), '~')} "
        "so scripts and cron can call it?",
        default=True,
    )
    sounds = confirm("Play the playsound-N chime when a command finishes?", default=True)

    legacy_found = {
        rc_file: find_legacy(read_rc(rc_file))
        for target in targets
        if target.name in shells
        for rc_file in target.rc_files
        if find_legacy(read_rc(rc_file))
    }
    replace_legacy = False
    if legacy_found:
        print()
        total = sum(len(names) for names in legacy_found.values())
        note(f"Found {total} hand-written wrappers from before che managed them:")
        for rc_file, names in legacy_found.items():
            print(
                f"  {colors.grey}{rc_file}: {', '.join(names[:6])}"
                f"{'…' if len(names) > 6 else ''}{colors.reset}"
            )
        replace_legacy = confirm(
            "Replace them with the generated ones? (a backup is written first)", default=True
        )

    missing = [
        name
        for name, entry in binary_status().items()
        if not entry["present"] and not entry["system"]
    ]
    install_deps = False
    if missing:
        print()
        note(f"Missing external tools: {', '.join(missing)}")
        for name in missing:
            hint = INSTALL_HINTS.get(name)
            if hint:
                print(f"  {colors.grey}{name}: {hint}{colors.reset}")
        if shutil.which("brew"):
            install_deps = confirm("Install them now with Homebrew?", default=False)

    print()
    plan = InstallPlan(
        shells=shells,
        python=python,
        sounds=sounds,
        path_shim=path_shim,
        replace_legacy=replace_legacy,
        dry_run=dry_run,
    )
    result = perform_install(plan)
    report(plan, result)

    if install_deps:
        print()
        install_missing_binaries(missing, dry_run=dry_run)

    print()
    success("Done. Start using it with:")
    print(
        f"  {colors.bold}exec {shells[0]}{colors.reset}   {colors.grey}(reload your shell){colors.reset}"
    )
    print(
        f"  {colors.bold}che{colors.reset}          {colors.grey}(browse every command){colors.reset}"
    )
    print(
        f"  {colors.bold}che doctor{colors.reset}   {colors.grey}(check the install){colors.reset}"
    )
    return 0


# Past tense for what happened, present tense for what a dry run would do.
DRY_VERB = {
    "created": "create",
    "updated": "update",
    "unchanged": "leave unchanged",
    "installed": "install",
    "removed": "remove",
    "regenerated": "regenerate",
}


def report(plan: InstallPlan, result: InstallResult) -> None:
    """Print what an install did, in the same shape for wizard and --yes."""
    colors = palette()

    def phrase(action: str) -> str:
        if not plan.dry_run:
            return action
        return f"{colors.yellow}would {DRY_VERB.get(action, action)}{colors.reset}"

    def short(path: Path) -> str:
        return str(path).replace(str(home()), "~")

    for rc_file, action in result.rc_actions:
        mark = (
            f"{colors.grey}={colors.reset}"
            if action == "unchanged"
            else f"{colors.green}✓{colors.reset}"
        )
        print(f"  {mark} {phrase(action)} block in {short(rc_file)}")

    for rc_file, names in result.legacy_removed.items():
        print(
            f"  {colors.green}✓{colors.reset} {phrase('removed')} "
            f"{len(names)} legacy wrappers from {short(Path(rc_file))}"
        )

    if result.generated:
        print(
            f"  {colors.green}✓{colors.reset} {phrase('regenerated')} "
            f"{len(result.generated)} files under shell/"
        )

    if plan.path_shim:
        mark = (
            f"{colors.grey}={colors.reset}"
            if result.shim == "unchanged"
            else f"{colors.green}✓{colors.reset}"
        )
        print(f"  {mark} che shim {phrase(result.shim)}: {short(shim_path())}")
        if not shim_on_path():
            print(
                f"  {colors.grey}  ({shim_path().parent} is added to PATH by the block){colors.reset}"
            )


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------

OK, WARN, FAIL = "ok", "warn", "fail"


def diagnose() -> list[dict]:
    """Collect every check as data, so both the table and --json use one source."""
    checks: list[dict] = []
    config = load_config()

    python, version = find_python()
    version_text = ".".join(str(part) for part in (version or ()))
    checks.append(
        {
            "name": "python",
            "status": OK if version and version[:2] >= MIN_PYTHON else FAIL,
            "detail": f"{version_text} ({python})",
            "fix": "brew install python@3.13",
        }
    )

    checks.append(
        {
            "name": "repo",
            "status": OK if (REPO / "bin" / "che.py").exists() else FAIL,
            "detail": str(REPO),
            "fix": "re-clone the repo",
        }
    )

    stale = check_generated()
    checks.append(
        {
            "name": "generated files",
            "status": OK if not stale else WARN,
            "detail": "current"
            if not stale
            else f"{len(stale)} out of date: " + ", ".join(str(path) for path in stale),
            "fix": "che install",
        }
    )

    installed_version = config.get("version")
    checks.append(
        {
            "name": "install record",
            "status": OK if installed_version == VERSION else (WARN if config else FAIL),
            "detail": f"config {installed_version or 'missing'} vs che {VERSION}",
            "fix": "che install",
        }
    )

    # Only the shells this install actually targets. Reporting on every shell
    # present would flag ~/.profile as "missing" on any machine with /bin/sh,
    # which is every machine.
    watched = set(config.get("shells") or default_shell_selection(detect_shells()))
    watched.add(login_shell())

    for target in detect_shells():
        if target.name not in watched:
            continue
        for rc_file in target.rc_files:
            text = read_rc(rc_file)
            has_block = find_block(text) is not None
            legacy = find_legacy(text)
            status = OK if has_block else (WARN if target.name == "sh" else FAIL)
            detail = "block installed" if has_block else "no che block"
            if legacy:
                status = WARN if has_block else status
                detail += f", {len(legacy)} legacy wrappers"

            shadowing = find_shadowing(text)
            if shadowing:
                status = WARN if status == OK else status
                detail += ", shadowed: " + ", ".join(
                    f"{name} ({how})" for name, how in shadowing[:3]
                )
                shadow_fix = (
                    "the alias wins at the prompt; run `\\name` for the wrapper, "
                    "or remove the alias"
                    if any(how == "alias" for _, how in shadowing)
                    else "move your definition above the che block"
                )
            checks.append(
                {
                    "name": f"{target.name}: {str(rc_file).replace(str(home()), '~')}",
                    "status": status,
                    "detail": detail,
                    "fix": (
                        "che install --replace-legacy"
                        if legacy
                        else (shadow_fix if shadowing else "che install")
                    ),
                }
            )

    shim = shim_path()
    if shim.exists() and shim_on_path():
        shim_status, shim_detail, shim_fix = OK, str(shim), ""
    elif shim.exists():
        shim_status = WARN
        shim_detail = f"{shim} (PATH picks it up on your next shell)"
        shim_fix = f"exec {login_shell() or 'zsh'}"
    else:
        shim_status, shim_detail, shim_fix = WARN, "not installed", "che install"
    checks.append(
        {"name": "che on PATH", "status": shim_status, "detail": shim_detail, "fix": shim_fix}
    )

    for binary, entry in binary_status().items():
        used_by = ", ".join(entry["commands"][:3])
        if len(entry["commands"]) > 3:
            used_by += f" +{len(entry['commands']) - 3}"
        checks.append(
            {
                "name": f"tool: {binary}",
                "status": OK if entry["present"] else WARN,
                "detail": entry["path"] or f"missing - needed by {used_by}",
                "fix": entry["hint"],
            }
        )

    missing_scripts = [
        command.name
        for command in all_commands()
        if command.script and not (REPO / "bin" / command.script).exists()
    ]
    checks.append(
        {
            "name": "scripts",
            "status": OK if not missing_scripts else FAIL,
            "detail": f"{len(all_commands())} commands"
            + ("" if not missing_scripts else f", missing: {', '.join(missing_scripts)}"),
            "fix": "git pull",
        }
    )

    return checks


def doctor(*, as_json: bool = False, verbose: bool = False) -> int:
    checks = diagnose()

    if as_json:
        print(json.dumps({"version": VERSION, "checks": checks}, indent=2))
        return 1 if any(check["status"] == FAIL for check in checks) else 0

    colors = palette()
    marks = {
        OK: f"{colors.green}✓{colors.reset}",
        WARN: f"{colors.yellow}!{colors.reset}",
        FAIL: f"{colors.red}✗{colors.reset}",
    }

    print_logo(f"doctor - che {VERSION}")
    width = max(len(check["name"]) for check in checks) + 2

    for check in checks:
        if check["status"] == OK and not verbose and check["name"].startswith("tool: "):
            continue
        line = f"  {marks[check['status']]} {check['name']:<{width}} {colors.grey}{check['detail']}{colors.reset}"
        print(line)
        if check["status"] != OK and check["fix"]:
            print(f"    {colors.grey}→ {check['fix']}{colors.reset}")

    failures = sum(1 for check in checks if check["status"] == FAIL)
    warnings = sum(1 for check in checks if check["status"] == WARN)
    print()
    if failures:
        warning(f"{failures} problem(s), {warnings} warning(s).")
    elif warnings:
        note(f"All good, with {warnings} warning(s).")
    else:
        success("Everything checks out.")
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# Update and uninstall
# ---------------------------------------------------------------------------


def update(*, check_only: bool = False, dry_run: bool = False) -> int:
    """Pull the latest scripts, then refresh whatever is installed.

    This is the "update the app itself" path: it moves the repo forward, then
    re-runs the install with the recorded settings so new commands get wrappers
    without the user having to remember a second step.
    """
    colors = palette()
    if not shutil.which("git"):
        warning("❌ git is not installed, so che cannot update itself.")
        return 1

    before = run(["git", "rev-parse", "HEAD"], cwd=REPO, capture=True, check=False).stdout.strip()

    info("Fetching…")
    fetch = run(["git", "fetch", "--prune"], cwd=REPO, check=False)
    if fetch.returncode != 0:
        warning("❌ git fetch failed.")
        return 1

    behind = run(
        ["git", "rev-list", "--count", "HEAD..@{upstream}"], cwd=REPO, capture=True, check=False
    )
    count = behind.stdout.strip() if behind.returncode == 0 else "?"

    if count == "0":
        success("Already up to date.")
    elif check_only:
        note(f"{count} commit(s) available. Run `che update` to apply.")
        return 0
    else:
        dirty = run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO,
            capture=True,
            check=False,
        ).stdout.strip()
        if dirty:
            warning("❌ The repo has uncommitted changes; not pulling.")
            note("   Commit or stash them, then run `che update` again.")
            return 1

        if dry_run:
            note(f"would pull {count} commit(s)")
        else:
            pull = run(["git", "pull", "--ff-only"], cwd=REPO, check=False)
            if pull.returncode != 0:
                warning("❌ git pull --ff-only failed - the branch has diverged.")
                return 1

    after = run(["git", "rev-parse", "HEAD"], cwd=REPO, capture=True, check=False).stdout.strip()
    if before and after and before != after:
        print()
        note("What changed:")
        log = run(
            ["git", "log", "--oneline", "--no-decorate", f"{before}..{after}"],
            cwd=REPO,
            capture=True,
            check=False,
        ).stdout
        for line in log.splitlines()[:20]:
            print(f"  {colors.grey}{line}{colors.reset}")

    if check_only:
        return 0

    config = load_config()
    if not config:
        note("che is not installed yet; running the installer.")
        return wizard(dry_run=dry_run)

    print()
    plan = InstallPlan(
        shells=config.get("shells", default_shell_selection(detect_shells())),
        python=find_python()[0],
        sounds=config.get("sounds", True),
        path_shim=config.get("path_shim", True),
        dry_run=dry_run,
    )
    result = perform_install(plan)
    report(plan, result)

    print()
    success("Updated. Reload your shell to pick up new commands:")
    print(f"  {colors.bold}exec {login_shell() or 'zsh'}{colors.reset}")
    return 0


def uninstall(*, dry_run: bool = False, purge: bool = False) -> int:
    colors = palette()
    touched = False

    for target in detect_shells():
        for rc_file in target.rc_files:
            if remove_block(rc_file, dry_run=dry_run):
                touched = True
                display = str(rc_file).replace(str(home()), "~")
                print(f"  {colors.green}✓{colors.reset} removed block from {display}")

    shim = shim_path()
    if shim.exists():
        touched = True
        if not dry_run:
            shim.unlink()
        print(f"  {colors.green}✓{colors.reset} removed {shim}")

    if purge and config_dir().exists():
        touched = True
        if not dry_run:
            shutil.rmtree(config_dir())
        print(f"  {colors.green}✓{colors.reset} removed {config_dir()}")
    elif config_file().exists() and not dry_run:
        config_file().unlink()

    if not touched:
        note("Nothing to remove - che was not installed here.")
    else:
        print()
        success("Uninstalled. The repo itself is untouched; delete it to finish.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_install_parser(prog: str = "che install"):
    parser = build_parser(
        prog=prog,
        description="📥 Install the che shell wrappers into your shell startup files.",
        epilog=(
            "Examples:\n"
            "  che install                        interactive first-run wizard\n"
            "  che install --yes                  install into the detected shells\n"
            "  che install --shells=zsh,fish      pick the shells yourself\n"
            "  che install --dry-run              show what would change\n"
            "  che install --replace-legacy       drop hand-written wrappers first\n"
            "  che install --print                print the rc block and exit"
        ),
    )
    parser.add_argument(
        "--shells",
        default="",
        metavar="LIST",
        help="Comma-separated: zsh, bash, fish, sh (default: detected)",
    )
    add_bool_flag(parser, "--all-shells", help="Install into every shell present on this machine")
    add_bool_flag(parser, "--yes", help="Skip the wizard and use the defaults")
    add_bool_flag(parser, "--dry-run", help="Report what would change, change nothing")
    add_bool_flag(
        parser,
        "--no-completions",
        dest="no_completions",
        allow_value=False,
        help="Skip installing tab completions",
    )
    add_bool_flag(
        parser,
        "--no-path-shim",
        dest="no_path_shim",
        allow_value=False,
        help="Do not put a `che` executable in ~/.local/bin",
    )
    add_bool_flag(
        parser,
        "--no-sounds",
        dest="no_sounds",
        allow_value=False,
        help="Do not call playsound-N when a command finishes",
    )
    add_bool_flag(
        parser,
        "--replace-legacy",
        dest="replace_legacy",
        help="Remove hand-written wrappers this repo now generates",
    )
    add_bool_flag(
        parser,
        "--install-deps",
        dest="install_deps",
        help="Install missing external tools with Homebrew",
    )
    add_bool_flag(parser, "--print", dest="print_block", help="Print the rc block and exit")
    add_bool_flag(parser, "--check", help="Verify the generated files are current (for CI)")
    add_bool_flag(parser, "--generate", help="Rewrite the files under shell/ and exit")
    return parser


def install_main(argv: list[str] | None = None) -> int:
    parser = build_install_parser()
    args = parser.parse_args(argv)

    if args.generate or args.check:
        try:
            _expected_files()
        except ValueError as exc:
            warning(f"❌ {exc}")
            return 1

    if args.generate:
        changed = write_generated(dry_run=args.dry_run)
        for relative in changed:
            note(f"wrote {relative}")
        success(f"✓ {len(changed) or 'no'} generated file(s) updated")
        return 0

    if args.check:
        stale = check_generated()
        if stale:
            warning("❌ Generated files are out of date:")
            for path in stale:
                note(f"   {path}")
            note("   Run `che install` (or `bun run generate`) and commit the result.")
            return 1
        success("✓ Generated shell files match bin/commands.py")
        return 0

    python, version = find_python()

    if args.print_block:
        shells = _requested_shells(args)
        for shell in shells:
            print(
                shellgen.rc_block(
                    WRAPPER_FOR_SHELL[shell], home=REPO, python=python, sounds=not args.no_sounds
                ),
                end="",
            )
        return 0

    if not args.yes and not args.shells and not args.all_shells and is_interactive():
        return wizard(dry_run=args.dry_run)

    if not version or version[:2] < MIN_PYTHON:
        warning(f"❌ Python {'.'.join(str(p) for p in MIN_PYTHON)}+ is required.")
        return 1

    plan = InstallPlan(
        shells=_requested_shells(args),
        python=python,
        sounds=not args.no_sounds,
        completions=not args.no_completions,
        path_shim=not args.no_path_shim,
        replace_legacy=args.replace_legacy,
        dry_run=args.dry_run,
    )

    print_logo(f"installing che {VERSION}")
    result = perform_install(plan)
    report(plan, result)

    if args.install_deps:
        missing = [
            name
            for name, entry in binary_status().items()
            if not entry["present"] and not entry["system"]
        ]
        if missing:
            print()
            install_missing_binaries(missing, dry_run=args.dry_run)

    print()
    success("Reload your shell to pick up the wrappers:  exec " + (login_shell() or "zsh"))
    return 0


def _requested_shells(args) -> list[str]:
    targets = detect_shells()
    if args.all_shells:
        return [target.name for target in targets if target.installed and target.name != "sh"]
    if args.shells:
        requested = [part.strip() for part in args.shells.split(",") if part.strip()]
        unknown = [name for name in requested if name not in RC_RESOLVERS]
        if unknown:
            warning(f"❌ Unknown shell(s): {', '.join(unknown)}")
            note(f"   Known: {', '.join(RC_RESOLVERS)}")
            sys.exit(1)
        return requested
    return default_shell_selection(targets)


def main() -> int:
    return install_main()


if __name__ == "__main__":
    from utils import run_cli

    run_cli(main)
