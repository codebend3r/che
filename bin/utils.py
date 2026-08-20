"""Shared helpers for the scripts under ``bin/<category>/``.

This is the Python counterpart of the older ``bin/utils.sh``. Scripts pick it
up with the same shape the shell scripts used for sourcing::

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from utils import info, warning, run

Everything here is standard library only, on purpose: the scripts have to run
from a bare ``python3`` on any machine this repo is cloned to, with no venv and
no install step.

=============================================================================
CLI conventions - shared patterns for bin/<category>/*.py

* Long flags only: ``--name=value`` for values (no space-separated ``-o val``
  style in these scripts unless a specific tool documents otherwise).
* Booleans: a bare ``--flag`` enables; the same flag also honors
  ``--flag=true|false`` (and yes|no, 1|0). ``add_bool_flag`` builds both forms.
  A bare ``--flag`` never consumes the following argument, matching the shell
  scripts' ``while [[ $# -gt 0 ]]`` loop.
* Help: ``-h`` / ``--help`` prints the script's usage.
* Parsing style: ``build_parser`` so every script handles argv the same way.
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from fnmatch import fnmatchcase
from pathlib import Path
from typing import NoReturn

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

NC = "\033[0m"  # No Color
RED = "\033[1;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[1;36m"
MAGENTA = "\033[1;35m"

_FORCE_COLOR_OFF = {"", "0", "false", "no", "off"}


def _color_enabled() -> bool:
    """Honor NO_COLOR and non-tty output the way a well-behaved CLI should.

    DELIBERATE DIVERGENCE from ``utils.sh``, which always emitted escapes.
    Suppressing them when stdout is not a terminal keeps captured output clean
    for the tests and for shell pipelines. ``FORCE_COLOR`` overrides, following
    the usual convention that ``FORCE_COLOR=0`` means off, not on.

    The tty check happens at call time, not import time, so
    ``contextlib.redirect_stdout`` and pytest's capture are both respected.
    """
    force = os.environ.get("FORCE_COLOR")
    if force is not None and force.lower() not in _FORCE_COLOR_OFF:
        return True
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except (ValueError, AttributeError):
        return False


def color_enabled() -> bool:
    """Public form of :func:`_color_enabled`, for callers that build their own
    escape sequences (per-language colouring, table headers) and must honour
    ``NO_COLOR`` the same way the log helpers do."""
    return _color_enabled()


def log_color(color: str, message: str) -> None:
    """Print ``message`` wrapped in ``color``.

    The shell original used ``printf '%b%b%b\\n'``, whose ``%b`` also expanded
    backslash escapes *inside the message* - so a Windows path or a regex in a
    log line came out mangled, and a stray ``\\c`` truncated the output. That
    escape expansion is deliberately not reproduced; messages print literally.

    Flushed on every line. Python block-buffers stdout when it is a pipe, but
    a subprocess writes its stderr straight to fd 2 - without the flush, git's
    error messages appear *before* the banner that introduced them whenever the
    output is piped to a file or a CI log.
    """
    if _color_enabled():
        print(f"{color}{message}{NC}", flush=True)
    else:
        print(message, flush=True)


def log(message: str) -> None:
    """Green. General progress."""
    log_color(GREEN, message)


def warning(message: str) -> None:
    """Red. Errors and destructive-action notices."""
    log_color(RED, message)


def info(message: str) -> None:
    """Cyan. Informational detail."""
    log_color(CYAN, message)


def note(message: str) -> None:
    """Yellow. Headers and secondary detail."""
    log_color(YELLOW, message)


def success(message: str) -> None:
    """Magenta. Summaries and completion."""
    log_color(MAGENTA, message)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_KB = 1024
_MB = _KB * 1024
_GB = _MB * 1024
_TB = _GB * 1024
_PB = _TB * 1024

_UNITS: tuple[tuple[int, str], ...] = (
    (_PB, "PB"),
    (_TB, "TB"),
    (_GB, "GB"),
    (_MB, "MB"),
    (_KB, "KB"),
)


def format_bytes(num_bytes: int) -> str:
    """Format a byte count as PB/TB/GB/MB/KB, or plain bytes below 1 KB.

    Truncates rather than rounds, matching ``utils.sh``, which piped through
    ``bc`` with ``scale=2``. ``2043`` bytes is ``1.99512...`` KB and renders as
    ``1.99 KB``, not ``2.00 KB``. The arithmetic is exact integer maths, so the
    truncation holds at every magnitude.

    Output is identical to the shell version for every value representable in
    bash's 64-bit signed arithmetic. Above 2^63 bash wrapped and fell through
    to a raw byte count; this version keeps formatting correctly.
    """
    num_bytes = int(num_bytes)

    for size, unit in _UNITS:
        if num_bytes >= size:
            # Integer maths, so the truncation is exact - Decimal's default
            # 28-digit context would round before the truncation could apply.
            hundredths = (num_bytes * 100) // size
            return f"{hundredths // 100}.{hundredths % 100:02d} {unit}"

    return f"{num_bytes} B"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

_TRUE_VALUES = {"true", "yes", "1", "on"}
_FALSE_VALUES = {"false", "no", "0", "off"}

# Suffix for the hidden companion option that sets a bool flag to False.
# Deliberately ugly so it cannot collide with a real flag name.
_FALSE_SUFFIX = "-set-false-internal"


def parse_bool(value: str | bool) -> bool:
    """Parse a boolean spelling.

    Accepts ``true|yes|1|on`` and ``false|no|0|off``, case-insensitive, and
    raises ``ValueError`` on anything else - so a typo like ``--dry-run=ture``
    is a hard error rather than a silent falsy that deletes the user's files.

    This is intentionally WIDER than the shell scripts, which tested dry-run
    with ``if $DRY_RUN; then`` - literally executing the value as a command.
    There ``true``/``false`` worked, ``1``/``0``/``on``/``off``/``no`` were
    "command not found", and ``yes`` invoked ``/usr/bin/yes`` and hung forever.
    """
    if isinstance(value, bool):
        return value

    lowered = value.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False

    raise ValueError(f"expected true/false (got: {value!r})")


class BoolFlagParser(argparse.ArgumentParser):
    """``ArgumentParser`` that handles ``--flag`` and ``--flag=value`` safely.

    argparse has no built-in for that pair. The obvious spelling,
    ``nargs="?"``, is a trap: it makes a bare ``--flag`` swallow the *next*
    argument whenever that argument parses as a boolean, so ``--dry-run 0``
    silently becomes ``dry_run=False`` and deletes for real. The shell scripts
    could never do that.

    Instead, ``--flag=value`` tokens are rewritten before argparse sees them:
    to ``--flag`` (a plain ``store_true``) for a true value, and to a hidden
    ``store_false`` companion for a false one. Rewriting in place keeps
    left-to-right precedence, so a later flag still wins over an earlier one.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._bool_flags: dict[str, str] = {}  # "--dry-run" -> "--dry-run-set-false-internal"

    def register_bool_flag(self, name: str, false_name: str) -> None:
        self._bool_flags[name] = false_name

    def _rewrite(self, argv: Sequence[str]) -> list[str]:
        rewritten: list[str] = []
        for index, arg in enumerate(argv):
            # Everything after a bare `--` is a literal positional, so it must
            # pass through untouched - rewriting it would report an error
            # naming an internal flag the user never typed.
            if arg == "--":
                rewritten.extend(argv[index:])
                break

            flag, sep, value = arg.partition("=")
            if not sep or flag not in self._bool_flags:
                rewritten.append(arg)
                continue
            try:
                enabled = parse_bool(value)
            except ValueError as exc:
                self.error(f"argument {flag}: {exc}")
            rewritten.append(flag if enabled else self._bool_flags[flag])
        return rewritten

    def parse_args(self, args=None, namespace=None):  # type: ignore[override]
        argv = list(sys.argv[1:] if args is None else args)
        return super().parse_args(self._rewrite(argv), namespace)

    def parse_known_args(self, args=None, namespace=None):  # type: ignore[override]
        argv = list(sys.argv[1:] if args is None else args)
        return super().parse_known_args(self._rewrite(argv), namespace)

    def error(self, message: str) -> NoReturn:
        """Print the message plus full usage and exit 1, as the shell did.

        argparse's default is a one-line usage and exit code 2. Every shell
        script here printed ``❌ Unknown argument: X`` followed by the whole
        usage block and exited 1, and the ``.zshrc`` chains distinguish 1 from
        other codes.

        Annotated ``NoReturn`` so callers - notably ``_rewrite``, which falls
        through to use a variable this branch never assigns - are provably safe.
        """
        # The hidden companion option is an implementation detail; a user who
        # typed `--dry-run=false` should not be told about it by name.
        warning(f"❌ {message.replace(_FALSE_SUFFIX, '')}")
        self.print_help()
        sys.exit(1)


def build_parser(prog: str, description: str, epilog: str = "") -> BoolFlagParser:
    """A parser pre-set to this repo's conventions.

    ``allow_abbrev=False`` matters: without it argparse silently accepts
    ``--dry`` for ``--dry-run``, which the shell scripts never did.
    """
    return BoolFlagParser(
        prog=prog,
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )


def add_bool_flag(
    parser: BoolFlagParser,
    name: str,
    *,
    default: bool = False,
    help: str = "",
    dest: str | None = None,
    allow_value: bool = True,
) -> None:
    """Add a flag accepting both ``--flag`` and ``--flag=true|false``.

    Both spellings are needed in most places: the shell scripts supported them,
    and the ``.zshrc`` wrappers rely on the ``=value`` form to flip dry-run
    defaults. See :class:`BoolFlagParser` for why this is not ``nargs="?"``.

    Pass ``allow_value=False`` for an inverted flag such as ``--no-force``.
    The shell scripts only ever accepted the bare spelling for those, and
    ``--no-force=false`` is a double negative nobody should have to decode: it
    would silently mean "do force", which is the opposite of how it reads on a
    script that unmounts volumes.
    """
    dest = dest or name.removeprefix("--").replace("-", "_")

    parser.add_argument(name, action="store_true", dest=dest, default=default, help=help)

    if not allow_value:
        return

    false_name = f"{name}{_FALSE_SUFFIX}"
    parser.add_argument(
        false_name, action="store_false", dest=dest, default=default, help=argparse.SUPPRESS
    )
    parser.register_bool_flag(name, false_name)


def env_bool(name: str, default: bool) -> bool:
    """Read a boolean from the environment, for the ``DRY_RUN=true`` wrappers.

    An unset or empty variable falls back to ``default``. An unparseable value
    exits non-zero rather than guessing, because guessing wrong on ``DRY_RUN``
    means deleting files the user expected only to preview.
    """
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return parse_bool(raw)
    except ValueError as exc:
        warning(f"❌ Environment variable {name}: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Subprocess
# ---------------------------------------------------------------------------


def require_binary(name: str, *, hint: str = "") -> str:
    """Exit with a clear message when an external tool is missing.

    Serves the same role as the ``require_binary`` helper in
    ``bin/video/find-video-mkv-issues.sh``, with a friendlier message and an
    optional install hint. Returns the resolved path so the caller can pass an
    absolute program name to :func:`run`.

    Note this resolves PATH executables only, where bash's ``command -v`` also
    found builtins, functions and aliases. Every binary this repo requires is a
    real executable, so the distinction does not bite in practice.
    """
    resolved = shutil.which(name)
    if resolved is None:
        warning(f"❌ '{name}' is not installed or not in PATH.")
        if hint:
            info(f"💡 {hint}")
        sys.exit(1)
    return resolved


def run(
    argv: Sequence[str],
    *,
    check: bool = True,
    capture: bool = False,
    cwd: str | Path | None = None,
    text: bool = True,
    env: dict[str, str] | None = None,
    stdin: int | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an external command.

    Always an argv list, never a string, and never ``shell=True`` - the two
    rules that keep quoting bugs and injection out of a script that handles
    arbitrary filenames. ``check=True`` by default so a failure raises instead
    of being sailed past, which is what ``set -e`` bought the shell versions.

    ``env`` ADDS to the current environment rather than replacing it, matching
    the shell idiom ``VAR=x cmd``. Replacing it outright would drop
    ``/opt/homebrew/bin`` from PATH and make ffmpeg and friends vanish.
    """
    merged_env = {**os.environ, **env} if env else None

    return subprocess.run(  # noqa: S603 - argv list, shell=False, by construction
        list(argv),
        check=check,
        capture_output=capture,
        cwd=cwd,
        text=text,
        # errors="replace" rather than the default "strict": a single
        # non-UTF-8 byte in a child's diagnostic (a legacy-encoded title tag
        # echoed back by ffmpeg, say) would otherwise raise UnicodeDecodeError
        # and abort a whole library scan partway through.
        errors="replace" if text else None,
        env=merged_env,
        stdin=stdin,
        timeout=timeout,
    )


def run_output(argv: Sequence[str], *, check: bool = True, cwd: str | Path | None = None) -> str:
    """Run a command and return its stdout with the trailing newline stripped.

    The equivalent of ``$(cmd)``. With ``check=False`` this is the equivalent of
    ``$(cmd) || true``: a non-zero exit still returns whatever stdout was
    produced, and a missing binary returns "" instead of raising.
    """
    try:
        completed = run(argv, check=check, capture=True, cwd=cwd)
    except FileNotFoundError:
        if check:
            raise
        return ""
    return (completed.stdout or "").rstrip("\n")


def run_lines(
    argv: Sequence[str], *, check: bool = True, cwd: str | Path | None = None
) -> list[str]:
    """Run a command and return stdout split into non-empty lines.

    DELIBERATE DIVERGENCE: in the shell scripts these reads sat inside
    ``< <(...)`` process substitution, whose failure does NOT trip ``set -e`` -
    a failing ``git for-each-ref`` just looked like "no branches" and the script
    exited 0. Here a failure raises.
    """
    output = run_output(argv, check=check, cwd=cwd)
    return [line for line in output.split("\n") if line]


def run_cli(entry: Callable[[], int]) -> None:
    """Run a script's ``main`` and translate exceptions into shell exit codes.

    Every script ends with ``run_cli(main)`` so error handling is identical
    across the repo, rather than each file growing its own ``try/except``.
    """
    try:
        sys.exit(entry())
    except subprocess.CalledProcessError as exc:
        # Surface the child's own diagnostic. The shell versions let stderr
        # through to the terminal; capturing it and printing only "command
        # failed" would hide git's actual explanation.
        if getattr(exc, "stderr", None):
            sys.stderr.write(exc.stderr)
        warning(f"❌ Command failed: {' '.join(str(part) for part in exc.cmd)}")
        code = exc.returncode
        # A negative returncode means the child died on a signal; shells report
        # that as 128+N, and sys.exit(-9) would otherwise become 247.
        sys.exit(128 - code if code and code < 0 else (code or 1))
    except FileNotFoundError as exc:
        warning(f"❌ {exc}")
        sys.exit(127)
    except OSError as exc:
        warning(f"❌ {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


# ---------------------------------------------------------------------------
# Worktrees
#
# A branch checked out in a linked worktree cannot be checked out, deleted or
# reset from the main clone - git refuses with "already used by worktree".
# That is a mechanical limit, not a conflict, so every script that touches
# branches needs to know which ones are pinned and where.
# ---------------------------------------------------------------------------


def worktree_branch_map(cwd: str | Path | None = None) -> dict[str, str]:
    """Map ``branch -> worktree path`` for every worktree with a branch checked out.

    Detached worktrees are skipped (they pin no branch). The main worktree IS
    included, because its branch is pinned for exactly the same reason.

    DELIBERATE DIVERGENCE: ``utils.sh`` emitted "<branch>\t<path>" lines that
    every caller re-parsed. A dict is the same data without the round trip, and
    it cannot be truncated by a path containing a tab.
    """
    mapping: dict[str, str] = {}
    path = ""
    branch = ""

    def flush() -> None:
        if path and branch:
            # First writer wins: a branch can only be pinned by one worktree,
            # so a duplicate would mean git contradicted itself.
            mapping.setdefault(branch, path)

    for line in run_output(["git", "worktree", "list", "--porcelain"], cwd=cwd).splitlines():
        if line.startswith("worktree "):
            # A new record starts; flush the previous one.
            flush()
            path = line.removeprefix("worktree ")
            branch = ""
        elif line.startswith("branch refs/heads/"):
            branch = line.removeprefix("branch refs/heads/")

    flush()
    return mapping


def worktree_for_branch(branch: str, cwd: str | Path | None = None) -> str:
    """The worktree path holding ``branch``, or "" when no worktree does."""
    return worktree_branch_map(cwd).get(branch, "")


def worktree_is_clean(path: str | Path) -> bool:
    """True when the worktree at ``path`` has no modified or untracked files.

    Ignored build output (node_modules, .next) does not count as dirty, because
    ``git status --porcelain`` does not list ignored paths.
    """
    completed = run(["git", "-C", str(path), "status", "--porcelain"], check=False, capture=True)
    # A non-zero exit means the path is not a working tree at all. Treating
    # that as "clean" would let a caller delete a directory it never inspected.
    if completed.returncode != 0:
        return False
    return not (completed.stdout or "").strip()


def branch_is_pushed(branch: str, cwd: str | Path | None = None) -> bool:
    """True when every commit on ``branch`` is already on its remote.

    Prefers the configured upstream and falls back to ``origin/<branch>``.
    """
    upstream = run_output(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{branch}@{{upstream}}"],
        check=False,
        cwd=cwd,
    ).strip()
    if not upstream:
        upstream = f"origin/{branch}"

    exists = run(
        ["git", "rev-parse", "--verify", "--quiet", upstream], check=False, capture=True, cwd=cwd
    )
    if exists.returncode != 0:
        return False

    ancestor = run(
        ["git", "merge-base", "--is-ancestor", branch, upstream],
        check=False,
        capture=True,
        cwd=cwd,
    )
    return ancestor.returncode == 0


def worktree_paths(cwd: str | Path | None = None) -> list[str]:
    """Every worktree path in ``git worktree list --porcelain`` order.

    The first entry is always the main worktree; callers drop it themselves so
    the distinction stays explicit at the call site.

    The shell version parsed this with ``awk '{print $2}'``, which splits on
    whitespace and so truncated any worktree path containing a space. Taking
    the whole remainder of the line keeps such paths intact.
    """
    return [
        line.removeprefix("worktree ")
        for line in run_output(["git", "worktree", "list", "--porcelain"], cwd=cwd).splitlines()
        if line.startswith("worktree ")
    ]


def main_worktree(cwd: str | Path | None = None) -> str:
    """The main worktree's path - the first record git lists, always."""
    paths = worktree_paths(cwd)
    return paths[0] if paths else ""


def find_main_branch(cwd: str | Path | None = None) -> str:
    """The local main branch, preferring ``main`` over ``master``, or "" for neither.

    Takes an explicit ``cwd`` because callers run it after moving to the main
    worktree; relying on the process working directory would make the answer
    depend on where the script happened to be invoked from.
    """
    for candidate in ("main", "master"):
        exists = run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"],
            check=False,
            capture=True,
            cwd=cwd,
        )
        if exists.returncode == 0:
            return candidate
    return ""


# ---------------------------------------------------------------------------
# ffprobe
# ---------------------------------------------------------------------------


def ffprobe_entries(
    path: Path,
    entries: str,
    *,
    stream: str | None = None,
    fmt: str = "csv=p=0",
    on_error: str = "",
) -> str:
    """Read metadata out of a media file with ffprobe.

    ``entries`` is passed straight to ``-show_entries`` (e.g.
    ``stream=codec_name``). ``stream`` selects a stream when given (e.g.
    ``v:0``).

    Returns ``on_error`` when ffprobe itself fails, and "" when it succeeds but
    the field is absent. Those are different situations - a corrupt file versus
    a file with no audio track - and callers need to tell them apart.
    """
    argv = ["ffprobe", "-v", "error"]
    if stream is not None:
        argv += ["-select_streams", stream]
    argv += ["-show_entries", entries, "-of", fmt, str(path)]

    completed = run(argv, check=False, capture=True)
    if completed.returncode != 0:
        return on_error
    return (completed.stdout or "").strip()


def ffprobe_json(path: Path, argv_extra: Sequence[str]) -> dict:
    """Run ffprobe with ``-of json`` and parse the result.

    Returns an empty dict when ffprobe fails or emits unparseable output, so
    callers can treat an unreadable file as "no streams" rather than crashing
    partway through a large library scan.
    """
    argv = ["ffprobe", "-v", "error", *argv_extra, "-of", "json", str(path)]
    completed = run(argv, check=False, capture=True)
    if completed.returncode != 0:
        return {}
    try:
        parsed = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


def is_macos_metadata(path: Path) -> bool:
    """True for the AppleDouble sidecars (``._foo``) the shell scripts skipped.

    ``.DS_Store`` is deliberately not included: the scripts that skip metadata
    are matching the ``._*`` pattern specifically.
    """
    return path.name.startswith("._")


def iter_files(
    root: Path,
    *,
    extensions: Iterable[str] | None = None,
    recursive: bool = True,
    skip_macos_metadata: bool = True,
    skip_hidden: bool = False,
    case_sensitive: bool = False,
) -> Iterator[Path]:
    """Walk ``root`` yielding files, the replacement for ``find ... -print0``.

    Streams like ``find`` did: constant memory, first result immediately, and
    entries are printed as they are found rather than after a full scan. On a
    multi-TB media library that is the difference between instant output and a
    minutes-long silent stall. Order within each directory is sorted, so runs
    are reproducible without buffering the whole tree.

    ``extensions`` is matched against the end of the FILENAME, reproducing
    ``find -iname '*.ext'`` exactly - including for a file literally named
    ``.mkv``, which a ``Path.suffix`` check would miss because pathlib treats a
    leading dot as the stem. Pass ``case_sensitive=True`` for the handful of
    callers whose shell original used ``-name`` rather than ``-iname``.

    Only regular files are yielded. ``find -type f`` excluded FIFOs, sockets
    and devices, and a FIFO reaching an ``open()`` blocks forever - which on a
    hashing pass would hang the whole scan.

    Symlinked files are skipped and symlinked directories are not followed,
    matching ``find``'s default (no ``-L``).

    Raises ``FileNotFoundError`` when ``root`` is not a directory. ``find``
    errored there too, and under ``set -e`` that aborted the run; silently
    yielding nothing would make a typo'd ``--path`` look like a clean library.
    """
    if not root.is_dir():
        raise FileNotFoundError(f"Not a directory: {root}")

    patterns: tuple[str, ...] | None = None
    if extensions is not None:
        patterns = tuple(f"*.{ext}" if case_sensitive else f"*.{ext.lower()}" for ext in extensions)

    def _on_error(exc: OSError) -> None:
        # find(1) printed "Permission denied" to stderr and carried on. Staying
        # silent would make a half-readable SMB share look fully scanned.
        # stderr, not the usual warning() helper, so these lines never
        # interleave into output a caller is piping.
        print(f"find: {exc.filename}: {exc.strerror}", file=sys.stderr, flush=True)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=_on_error):
        dirnames.sort()
        if skip_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        filenames.sort()

        directory = Path(dirpath)
        for name in filenames:
            if skip_macos_metadata and name.startswith("._"):
                continue
            if skip_hidden and name.startswith("."):
                continue
            candidate = name if case_sensitive else name.lower()
            if patterns is not None and not any(
                fnmatchcase(candidate, pattern) for pattern in patterns
            ):
                continue
            path = directory / name
            if path.is_symlink() or not path.is_file():
                continue
            yield path

        if not recursive:
            dirnames[:] = []


def scan_root(raw: str, *, flag: str = "--path") -> Path:
    """Validate a user-supplied scan root, or exit with a clear message.

    Refuses a symlinked root. That is not fussiness: ``find`` does not follow a
    symlinked START POINT without ``-L``, so every shell script here was a
    silent no-op when pointed at one. Quietly descending instead would turn
    ``delete-by-ext --path=~/media`` (a symlink to the NAS) from "does nothing"
    into "deletes the library". Refusing is the only safe reading of a case the
    shell version never actually handled.
    """
    if not raw:
        warning(f"❌ {flag} is required")
        sys.exit(1)

    path = Path(raw)

    if path.is_symlink():
        warning(f"❌ {flag} is a symlink: {raw}")
        info("💡 find(1) does not follow a symlinked start point, so this was")
        info("   previously a no-op. Pass the real path to act on it.")
        sys.exit(1)

    if not path.is_dir():
        warning(f"❌ Directory not found: {raw}")
        sys.exit(1)

    return path


def normalize_extensions(raw: str, *, flag: str = "--ext") -> list[str]:
    """Split a comma-separated extension list, preserving glob metacharacters.

    Values are passed through verbatim (minus surrounding whitespace) so
    ``--ext=mp*`` still matches mp4/mp3/mpg, exactly as the shell version's
    ``-iname "*.$e"`` interpolation did.

    A leading dot is REJECTED rather than stripped. ``--ext=.jpg`` built
    ``-iname "*..jpg"`` in the shell version, which matched nothing - so
    stripping the dot would silently turn a harmless typo into a mass delete,
    and keeping it would silently match nothing. An error is the honest answer.
    """
    extensions = [part.strip() for part in raw.split(",")]
    extensions = [ext for ext in extensions if ext]

    for ext in extensions:
        if ext.startswith("."):
            warning(f"❌ {flag} entries must not start with a dot (got: {ext!r})")
            info(f"💡 Use {flag}={ext.lstrip('.')} instead.")
            sys.exit(1)

    return extensions


_SIZE_RE = re.compile(r"([0-9]+)([a-z]*)")


def parse_size(text: str) -> int:
    """Parse a human size like ``1MB``/``500k``/``2 GiB`` into bytes.

    Ports ``parse_bytes`` from ``files-under-size.sh``, and deliberately keeps
    its unit set: bytes, KB, MB, GB. Terabytes are NOT accepted - the shell
    version rejected them, and silently widening the accepted range of a flag
    that drives ``rm`` is how ``--size=1t`` turns into a deleted library.

    Binary units throughout (KB == KiB == 1024), as in the shell version.
    Unlike the shell version, a leading zero is decimal, not octal (``010mb``
    is 10 MB, not 8 MB), and a signed value is rejected outright.
    """
    cleaned = "".join(text.split()).lower()
    match = _SIZE_RE.fullmatch(cleaned)
    if match is None:
        raise ValueError(f"Invalid size: {text!r}")

    digits, unit = match.groups()

    multipliers = {
        "": 1,
        "b": 1,
        "k": _KB,
        "kb": _KB,
        "kib": _KB,
        "m": _MB,
        "mb": _MB,
        "mib": _MB,
        "g": _GB,
        "gb": _GB,
        "gib": _GB,
    }

    if unit not in multipliers:
        raise ValueError(f"Invalid size unit in {text!r}")

    return int(digits) * multipliers[unit]
