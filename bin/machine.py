"""Facts about the machine che is installed on.

Where che keeps its config, which shells exist and which rc files each one
reads, which python can run the scripts, which external tools are missing, and
whether this copy of che is a git clone. The installer, the doctor and the
dispatcher all ask these questions; the install record is the only thing
written from here.

Every path is resolved from the environment at call time, never at import
time, so the tests can point HOME at a temporary directory.

Library module: no shebang, not executable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

from commands import PACKAGE_NAME, REPO, required_binaries
from utils import atomic_write_text, run

# ---------------------------------------------------------------------------
# External tools
# ---------------------------------------------------------------------------

# Binary -> the Homebrew formula that provides it, which is what
# `che install --install-deps` installs.
BREW_FORMULA: dict[str, str] = {
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffmpeg",
    "mpv": "mpv",
    "exiftool": "exiftool",
    "gh": "gh",
    "btop": "btop",
    "git": "git",
}

# Binary -> how to get it. Anything absent from here is either part of macOS or
# has no obvious one-liner, and doctor says so rather than inventing a command.
INSTALL_HINTS: dict[str, str] = {
    **{binary: f"brew install {formula}" for binary, formula in BREW_FORMULA.items()},
    "brew": 'bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
}

# Binaries that ship with macOS: never suggest installing them, just report.
SYSTEM_BINARIES = frozenset({"diskutil", "osascript"})


def missing_binaries() -> list[str]:
    """Tools some command needs that are not on PATH, in name order, macOS's own aside."""
    return [
        binary
        for binary in required_binaries()
        if binary not in SYSTEM_BINARIES and not shutil.which(binary)
    ]


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


def home() -> Path:
    return Path(os.environ.get("HOME", str(Path.home())))


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or home() / ".config")


def config_dir() -> Path:
    return xdg_config_home() / "che"


def config_file() -> Path:
    return config_dir() / "config.json"


def backup_dir() -> Path:
    return config_dir() / "backups"


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or home() / ".local" / "state") / "che"


def shim_path() -> Path:
    return home() / ".local" / "bin" / "che"


def shim_on_path() -> bool:
    entries = os.environ.get("PATH", "").split(os.pathsep)
    return str(shim_path().parent) in entries


def tildify(path: Path) -> str:
    """``path`` for display, with the home directory spelled ``~``."""
    try:
        return f"~/{path.relative_to(home())}"
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Shells
# ---------------------------------------------------------------------------


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
    return [xdg_config_home() / "fish" / "config.fish"]


def _sh_rc_files() -> list[Path]:
    return [home() / ".profile"]


def login_shell() -> str:
    return Path(os.environ.get("SHELL", "")).name


@dataclass(frozen=True)
class ShellSpec:
    """A shell che can install into, how, and how it stands on this machine.

    The properties are read from the environment each time they are asked, so
    a test that moves HOME or ZDOTDIR sees the move.
    """

    name: str
    find_rc_files: Callable[[], list[Path]]
    # The generated file the block sources, `shell/che.<flavor>`, and so the
    # syntax the block itself is written in.
    flavor: str
    # Never installed into unless asked for, and a missing block only warns.
    opt_in: bool = False

    @property
    def rc_files(self) -> list[Path]:
        """The rc files an install into this shell writes."""
        return self.find_rc_files()

    @property
    def installed(self) -> bool:
        """Whether the shell itself exists on this machine."""
        return shutil.which(self.name) is not None

    @property
    def has_rc(self) -> bool:
        return any(path.exists() for path in self.rc_files)

    @property
    def is_login_shell(self) -> bool:
        return self.name == login_shell()


SHELLS: dict[str, ShellSpec] = {
    spec.name: spec
    for spec in (
        ShellSpec("zsh", _zsh_rc_files, "zsh"),
        ShellSpec("bash", _bash_rc_files, "bash"),
        ShellSpec("fish", _fish_rc_files, "fish"),
        # `sh` reuses the bash wrapper file: it is plain POSIX shell apart from
        # the completion tail, which is guarded by a $BASH_VERSION test. Opt-in,
        # because `.profile` is read by every POSIX shell on the machine, which
        # is rarely what someone means.
        ShellSpec("sh", _sh_rc_files, "bash", opt_in=True),
    )
}


def default_shell_selection() -> list[str]:
    """What to install into when the user does not say.

    The login shell always, plus any other shell that is both installed and
    already has an rc file - those are shells the user demonstrably uses.
    Opt-in shells are never chosen here.
    """
    specs = [spec for spec in SHELLS.values() if not spec.opt_in]
    chosen = [spec.name for spec in specs if spec.is_login_shell]
    chosen += [
        spec.name for spec in specs if spec.name not in chosen and spec.installed and spec.has_rc
    ]
    return chosen or ["zsh"]


# ---------------------------------------------------------------------------
# The install record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstallRecord:
    """What ``config.json`` keeps about an install.

    ``che update`` repeats the install from it, ``che doctor`` checks against
    it, and its absence is how the dispatcher knows to run the first-run
    wizard. Every field has a default so a record an older che wrote, missing
    a key, still loads.
    """

    version: str = ""
    home: str = ""
    python: str = ""
    shells: list[str] = field(default_factory=list)
    rc_files: list[str] = field(default_factory=list)
    sounds: bool = True
    path_shim: bool = True
    installed_at: str = ""


def load_record() -> InstallRecord | None:
    """The recorded install, or None when there is none.

    A missing, unreadable or empty file, or one that does not hold a JSON
    object, all read as "not installed". Keys this che does not know (older
    records carried ``completions``) are ignored, and an empty ``shells``
    means the default selection - so ``che update``, which reinstalls into
    them, and ``che doctor``, which checks them, agree on what it means.
    """
    try:
        data = json.loads(config_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data:
        return None

    known = {entry.name for entry in fields(InstallRecord)}
    record = InstallRecord(**{key: value for key, value in data.items() if key in known})
    return record if record.shells else replace(record, shells=default_shell_selection())


def save_record(record: InstallRecord, *, dry_run: bool = False) -> None:
    if dry_run:
        return
    atomic_write_text(config_file(), json.dumps(asdict(record), indent=2) + "\n")


# ---------------------------------------------------------------------------
# Python interpreter
# ---------------------------------------------------------------------------

MIN_PYTHON = (3, 12)
PYTHON_HINT = "brew install python@3.13"


def version_text(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


MIN_PYTHON_TEXT = version_text(MIN_PYTHON)


def python_ok(version: tuple[int, ...]) -> bool:
    return tuple(version[:2]) >= MIN_PYTHON


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


def find_python() -> tuple[str, tuple[int, ...]]:
    """Pick the interpreter the wrappers should use.

    The interpreter running this script wins when it is new enough - it is the
    one the user just proved works. Otherwise fall back to the newest suitable
    ``python3.X`` on PATH. macOS matters here: ``/usr/bin/python3`` is whatever
    the Command Line Tools shipped, often years behind the Homebrew python that
    is also installed. With nothing suitable anywhere, the running interpreter
    comes back anyway, and the caller reports it as too old.
    """
    if python_ok(sys.version_info):
        return sys.executable, sys.version_info[:3]

    for candidate in ("python3.14", "python3.13", "python3.12", "python3"):
        resolved = shutil.which(candidate)
        if not resolved:
            continue
        version = python_version(resolved)
        if version and python_ok(version):
            return resolved, version

    return sys.executable, sys.version_info[:3]


# ---------------------------------------------------------------------------
# Where this copy of che came from
# ---------------------------------------------------------------------------


def is_git_checkout() -> bool:
    """Whether this copy of che is a clone, which ``che update`` can pull.

    The npm package is the same tree without ``.git``.
    """
    return (REPO / ".git").exists()


def update_command() -> str:
    """The command that fetches a newer che for this kind of install."""
    if is_git_checkout():
        return "git pull"
    return f"npm install -g {PACKAGE_NAME}@latest"
