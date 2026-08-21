"""Canonical registry of every command ``che`` exposes.

This module is the single source of truth for the user-facing command surface.
Four things are generated from it, so they can never drift apart:

* the shell wrappers in ``shell/che.zsh``, ``shell/che.bash`` and
  ``shell/che.fish`` (written by ``bin/install.py``),
* the tab completions under ``shell/completions/``,
* the interactive menu in ``bin/che.py``,
* the dependency report printed by ``che doctor``.

Before this file existed, ``.zshrc`` was the source of truth and every new
script meant hand-editing a wrapper into it - and hand-mirroring that edit into
``~/.zshrc``. Adding a script now means adding one :class:`Command` here and
running ``che install``.

Library module: no shebang, not executable, imported the same way as
``utils.py``::

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from commands import COMMANDS, resolve
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

BIN = Path(__file__).resolve().parent
REPO = BIN.parent

# Version of the `che` app itself - the dispatcher, the installer and the
# generated shell files together. Bump it when the generated output changes
# shape, because `che doctor` compares it against the version recorded in the
# installed rc block to decide whether a re-install is needed.
VERSION = "1.0.0"

# Suffix appended to a command name to get its preview-only twin.
DRY_SUFFIX = "-dr"


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    icon: str
    blurb: str


CATEGORIES: tuple[Category, ...] = (
    Category("git", "Git", "", "Branch hygiene, worktrees and GitHub Actions"),
    Category("video", "Video", "", "Codecs, renaming, dedupe and metadata"),
    Category("files", "Files", "", "Delete, compress and inspect by size or extension"),
    Category("drives", "Drives", "", "Mount, eject and keep-alive for the NAS volumes"),
    Category("system", "System", "", "Homebrew, monitoring and the machine itself"),
    Category("che", "che", "", "Install, update and inspect che itself"),
)

CATEGORY_KEYS = tuple(category.key for category in CATEGORIES)


# ---------------------------------------------------------------------------
# Prompts
#
# The interactive menu asks for these before running a command. They are
# curated rather than derived from `--help`, because "the two flags a human
# actually sets" is a smaller and better-ordered list than "every flag the
# script accepts" - anything else can still be typed at the extra-args line.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Prompt:
    """One question the interactive menu asks before running a command."""

    flag: str  # "--path"; empty string means a positional argument
    label: str
    kind: str = "text"  # text | path | size | int | bool | choice
    required: bool = False
    default: str = ""
    choices: tuple[str, ...] = ()
    help: str = ""

    @property
    def key(self) -> str:
        """Stable identity for per-prompt input history."""
        return self.flag.removeprefix("--") or "args"


PATH_PROMPT = Prompt("--path", "Path to scan", kind="path", required=True)
PATH_PROMPT_CWD = Prompt("--path", "Path to scan", kind="path", default=".")
DRY_PROMPT = Prompt("--dry-run", "Dry run (preview only)", kind="bool", default="true")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Command:
    """One user-facing command: a name, a script and how to invoke it."""

    name: str
    category: str
    summary: str
    script: str = ""  # relative to bin/; empty for a shell-only wrapper
    icon: str = "•"
    sound: int | None = None
    dry_sound: int | None = 7
    env: tuple[tuple[str, str], ...] = ()
    args: tuple[str, ...] = ()  # fixed arguments, always passed first
    flags: tuple[str, ...] = ()  # every flag the script accepts, for completions
    prompts: tuple[Prompt, ...] = ()
    needs: tuple[str, ...] = ()  # external binaries the script shells out to
    dry_run: str = ""  # "" | "env" (DRY_RUN=) | "flag" (--dry-run)
    destructive: bool = False
    # Set only where a destructive command genuinely cannot preview, with the
    # reason. The menu shows it, and the manifest test demands one rather than
    # letting a missing dry-run pass unnoticed.
    no_preview_reason: str = ""
    # One-off setup a command needs that `needs` cannot express, because it is
    # not a binary on PATH (a venv, a credential, a mounted volume).
    setup: str = ""
    macos_only: bool = False
    body: str = ""  # shell-only wrapper body, for commands with no script
    tags: tuple[str, ...] = ()
    builtin: bool = False  # handled by che.py itself, not a script

    @property
    def has_dry_twin(self) -> bool:
        """Whether a ``-dr`` wrapper is generated alongside this command."""
        return bool(self.dry_run)

    @property
    def dry_name(self) -> str:
        return f"{self.name}{DRY_SUFFIX}"

    @property
    def path(self) -> Path:
        return BIN / self.script

    def search_text(self) -> str:
        return " ".join((self.name, self.summary, self.category, *self.tags)).lower()

    def invocation(self, *, dry: bool = False) -> tuple[dict[str, str], list[str]]:
        """Environment overrides and fixed arguments for one invocation.

        ``dry`` selects the preview form: either ``DRY_RUN=true`` or an added
        ``--dry-run``, depending on how the underlying script spells it.
        """
        env = dict(self.env)
        args = list(self.args)

        if self.dry_run == "env":
            env["DRY_RUN"] = "true" if dry else "false"
        elif self.dry_run == "flag" and dry:
            args.append("--dry-run")

        return env, args


def _cmd(**kwargs: object) -> Command:
    """Keyword-only constructor, so a long table stays readable and greppable."""
    return Command(**kwargs)  # type: ignore[arg-type]


COMMANDS: tuple[Command, ...] = (
    # -- git ----------------------------------------------------------------
    _cmd(
        name="all-actions",
        flags=("--owner", "--author", "--pr-limit", "--interval", "--watch"),
        category="git",
        icon="🎬",
        summary="GitHub Actions status for every open PR you authored",
        script="git/all-actions.py",
        needs=("gh", "git"),
        tags=("ci", "pr", "github", "workflow"),
        prompts=(
            Prompt("--owner", "Only this owner", help="Defaults to every repo you own"),
            Prompt("--pr-limit", "PRs per repo", kind="int"),
        ),
    ),
    _cmd(
        name="all-actions-watch",
        flags=("--owner", "--author", "--pr-limit", "--interval"),
        category="git",
        icon="👀",
        summary="Same as all-actions, refreshed on an interval",
        script="git/all-actions.py",
        args=("--watch",),
        needs=("gh", "git"),
        tags=("ci", "pr", "github", "watch"),
    ),
    _cmd(
        name="checkout-my-branches",
        flags=("--author", "--limit"),
        category="git",
        icon="🌿",
        summary="Check out recent remote branches you authored that aren't local yet",
        script="git/checkout-my-branches.py",
        sound=7,
        needs=("git",),
        tags=("branch", "remote"),
        prompts=(
            Prompt("--author", "Author email", help="Defaults to git config user.email"),
            Prompt("--limit", "Remote branches to scan", kind="int"),
        ),
    ),
    _cmd(
        name="clean-stale-branches",
        flags=("--dry-run", "--protect"),
        category="git",
        icon="🧹",
        summary="Delete local branches whose upstream is gone",
        script="git/clean-stale-branches.py",
        sound=4,
        dry_run="env",
        destructive=True,
        needs=("git",),
        tags=("branch", "delete", "prune"),
        prompts=(Prompt("--protect", "Extra branches to protect", help="Comma separated"),),
    ),
    _cmd(
        name="prune-worktrees",
        flags=("--dry-run", "--force"),
        category="git",
        icon="🌳",
        summary="Remove every linked worktree, then prune stale admin records",
        script="git/prune-worktrees.py",
        sound=4,
        dry_run="env",
        destructive=True,
        needs=("git",),
        tags=("worktree", "prune", "delete"),
    ),
    _cmd(
        name="sync-all-branches",
        flags=("--dry-run", "--no-push", "--keep-locked", "--author", "--limit"),
        category="git",
        icon="🔄",
        summary="Push every worktree, collapse the pushed ones, then tidy branches",
        script="git/sync-all-branches.py",
        sound=7,
        dry_sound=7,
        dry_run="env",
        destructive=True,
        needs=("git",),
        tags=("push", "worktree", "branch", "sync"),
    ),
    _cmd(
        name="update-from-origin",
        flags=("--dry-run", "--keep-locked", "--author", "--limit"),
        category="git",
        icon="⬇️",
        summary="Same as sync-all-branches but never pushes: fetch, collapse, rebase",
        script="git/sync-all-branches.py",
        args=("--no-push",),
        env=(("DRY_RUN", "false"),),
        sound=7,
        needs=("git",),
        tags=("pull", "fetch", "sync", "worktree"),
    ),
    _cmd(
        name="update-local-branches",
        flags=("--limit", "--dry-run"),
        category="git",
        icon="⬆️",
        summary="Rebase every local branch that has an upstream onto origin",
        script="git/update-local-branches.py",
        sound=5,
        needs=("git",),
        tags=("rebase", "branch"),
        prompts=(
            Prompt("--limit", "Only the N most recent branches", kind="int"),
            DRY_PROMPT,
        ),
    ),
    # -- video --------------------------------------------------------------
    _cmd(
        name="show-codecs",
        flags=("--path", "--verbose"),
        category="video",
        icon="🎥",
        summary="Report media files outside the Direct Play codec/container set",
        script="video/show-codecs.py",
        sound=6,
        needs=("ffprobe",),
        tags=("plex", "codec", "audit"),
        prompts=(PATH_PROMPT, Prompt("--verbose", "Also print files that pass", kind="bool")),
    ),
    _cmd(
        name="fix-codecs",
        flags=("--path", "--delete-original", "--dry-run"),
        category="video",
        icon="🔧",
        summary="Re-encode media to h265/aac mp4 so it Direct Plays",
        script="video/fix-codecs.py",
        sound=7,
        dry_sound=7,
        dry_run="env",
        destructive=True,
        needs=("ffmpeg",),
        tags=("plex", "encode", "transcode"),
        prompts=(
            PATH_PROMPT,
            Prompt("--delete-original", "Delete each source after converting", kind="bool"),
        ),
    ),
    _cmd(
        name="find-video-mkv-issues",
        flags=("--path", "--recursive"),
        category="video",
        icon="🎬",
        summary="Scan MKV files and estimate Plex direct-play compatibility",
        script="video/find-video-mkv-issues.py",
        sound=4,
        needs=("ffprobe",),
        tags=("plex", "mkv", "audit"),
        prompts=(PATH_PROMPT, Prompt("--recursive", "Recurse into subfolders", kind="bool")),
    ),
    _cmd(
        name="validate-video-files",
        flags=("--path", "--verbose"),
        category="video",
        icon="🩺",
        summary="Check .mp4/.mkv files decode by playing one frame with mpv",
        script="video/validate-video-files.py",
        sound=2,
        needs=("mpv",),
        tags=("corrupt", "health", "audit"),
        prompts=(PATH_PROMPT, Prompt("--verbose", "Print each file as it is checked", kind="bool")),
    ),
    _cmd(
        name="scan-videos-audio-language",
        flags=("--path"),
        category="video",
        icon="🔊",
        summary="Print the audio language tags of every video under a path",
        script="video/scan-videos-audio-language.py",
        sound=3,
        needs=("ffprobe",),
        tags=("audio", "language", "dub"),
        prompts=(PATH_PROMPT,),
    ),
    _cmd(
        name="remove-metadata",
        flags=("--path", "--exts"),
        category="video",
        icon="🧼",
        summary="Strip all metadata from video files recursively",
        script="video/remove-metadata.py",
        sound=4,
        destructive=True,
        no_preview_reason="exiftool rewrites in place; the script has no preview mode",
        needs=("exiftool",),
        tags=("metadata", "tags", "plex"),
        prompts=(PATH_PROMPT, Prompt("--exts", "Extensions", help="Comma separated")),
    ),
    _cmd(
        name="rename-video-file",
        flags=(
            "--path",
            "--recursive",
            "--rename-folders",
            "--capitalize-preps",
            "--dry-run",
            "--ignore-words",
        ),
        category="video",
        icon="📝",
        summary="Title-case video filenames (and optionally their folders)",
        script="video/rename-video-file.py",
        sound=5,
        # No -dr twin: this script already defaults to --dry-run=true on its
        # own (it never read DRY_RUN, so an exported DRY_RUN=false in the
        # user's shell could not turn a preview into a mass rename). The
        # preview twin would be identical to the plain wrapper.
        destructive=True,
        tags=("rename", "title", "case"),
        prompts=(
            PATH_PROMPT,
            Prompt("--recursive", "Recurse into subdirectories", kind="bool", default="true"),
            Prompt("--rename-folders", "Rename folders too", kind="bool"),
            Prompt("--dry-run", "Preview only", kind="bool", default="true"),
            Prompt("--ignore-words", "Words to leave as written", help="Comma separated"),
        ),
    ),
    _cmd(
        name="delete-duplicate-videos",
        flags=("--path", "--strategy", "--dry-run", "--verbose"),
        category="video",
        icon="🗑️",
        summary="Delete duplicate MKV/MP4 files under a root directory",
        script="video/delete-duplicate-videos.py",
        sound=6,
        dry_sound=6,
        dry_run="env",
        destructive=True,
        tags=("duplicate", "delete", "dedupe"),
        prompts=(
            PATH_PROMPT,
            Prompt(
                "--strategy",
                "Match strategy",
                kind="choice",
                choices=("episode", "filename", "size", "hash", "all"),
                default="episode",
            ),
        ),
    ),
    _cmd(
        name="video-list",
        flags=("--path", "--recursive", "--with-folder", "--sort"),
        category="video",
        icon="📋",
        summary="List .mp4/.mkv files under a path with human-readable sizes",
        script="video/video-list.py",
        sound=5,
        tags=("list", "size"),
        prompts=(
            PATH_PROMPT,
            Prompt("--recursive", "Recurse into subdirectories", kind="bool"),
            Prompt(
                "--sort",
                "Sort order",
                kind="choice",
                choices=("alpha", "fileSizeAsc", "fileSizeDesc"),
                default="alpha",
            ),
        ),
    ),
    _cmd(
        name="detect-green-magenta-videos",
        flags=("--samples", "--threshold", "--verbose"),
        category="video",
        icon="🟢",
        summary="Detect videos with the green/magenta chroma artifact",
        script="video/detect-green-magenta-videos.py",
        sound=3,
        # The only command here that is not standard-library-only: it re-execs
        # itself under a venv holding OpenCV. Not a binary on PATH, so `needs`
        # cannot express it and doctor must not claim to have checked it.
        setup="needs OpenCV in ~/.venvs/green-magenta (override with $DETECT_GM_PYTHON)",
        tags=("corrupt", "artifact", "opencv"),
        prompts=(Prompt("", "Files or folders to scan", kind="path", required=True),),
    ),
    _cmd(
        name="find-movie-by-year",
        flags=("--year", "--path"),
        category="video",
        icon="🎞️",
        summary='Find movie folders whose name ends with "(YYYY)"',
        script="video/find-movie-by-year.py",
        sound=2,
        tags=("movie", "year", "search"),
        prompts=(Prompt("--year", "Year", required=True), PATH_PROMPT_CWD),
    ),
    _cmd(
        name="largest-tv-shows",
        flags=("--path", "--limit", "--full-path", "--debug"),
        category="video",
        icon="📺",
        summary="Rank TV show folders in a library by total size on disk",
        script="video/largest-tv-shows.py",
        sound=2,
        tags=("size", "tv", "report"),
        prompts=(PATH_PROMPT, Prompt("--limit", "How many to list", kind="int", default="20")),
    ),
    # -- files --------------------------------------------------------------
    _cmd(
        name="delete-by-ext",
        flags=("--path", "--ext", "--dry-run", "--verbose"),
        category="files",
        icon="🗑️",
        summary="Delete files under a path matching a set of extensions",
        script="files/delete-by-ext.py",
        sound=6,
        dry_run="env",
        destructive=True,
        tags=("delete", "extension", "cleanup"),
        prompts=(PATH_PROMPT, Prompt("--ext", "Extensions", help="Comma separated")),
    ),
    _cmd(
        name="delete-empty-folders",
        flags=("--path", "--dry-run", "--verbose"),
        category="files",
        icon="🧹",
        summary="Delete truly-empty directories under a path, cascading upwards",
        script="files/delete-empty-folders.py",
        sound=6,
        dry_run="env",
        destructive=True,
        tags=("delete", "empty", "cleanup"),
        prompts=(PATH_PROMPT,),
    ),
    _cmd(
        name="delete-smb-files",
        flags=("--path", "--dry-run"),
        category="files",
        icon="🧽",
        summary="Delete .smbdelete* files left behind by an SMB share",
        script="files/delete-smb-files.py",
        sound=6,
        dry_run="env",
        destructive=True,
        tags=("delete", "smb", "nas", "cleanup"),
        prompts=(PATH_PROMPT,),
    ),
    _cmd(
        name="files-under-size",
        flags=("--path", "--size", "--dry-run"),
        category="files",
        icon="📉",
        summary="Find video files at or under a size threshold",
        script="files/files-under-size.py",
        sound=4,
        dry_run="env",
        destructive=True,
        tags=("size", "delete", "small"),
        prompts=(PATH_PROMPT, Prompt("--size", "Size threshold", kind="size", required=True)),
    ),
    _cmd(
        name="find-largest-files",
        flags=("--path", "--length", "--full-path"),
        category="files",
        icon="📊",
        summary="List the largest files under a path, biggest first",
        script="files/find-largest-files.py",
        sound=2,
        tags=("size", "report", "disk"),
        prompts=(
            PATH_PROMPT_CWD,
            Prompt("--length", "How many to list", kind="int", default="10"),
            Prompt("--full-path", "Print the whole path", kind="bool"),
        ),
    ),
    _cmd(
        name="make-alpha-dir",
        flags=("--path"),
        category="files",
        icon="🔤",
        summary="Create '#' and A-Z bucket folders under a parent directory",
        script="files/make-alpha-dir.py",
        sound=4,
        tags=("organize", "folders"),
        prompts=(PATH_PROMPT_CWD,),
    ),
    _cmd(
        name="compress-folders",
        flags=("--path", "--dry-run", "--verbose"),
        category="files",
        icon="📦",
        summary="Zip every immediate subfolder of a path at max compression",
        script="files/compress-folders.py",
        sound=7,
        tags=("zip", "archive", "compress"),
        prompts=(PATH_PROMPT, DRY_PROMPT),
    ),
    _cmd(
        name="list-permission",
        flags=(),
        category="files",
        icon="🔐",
        summary="Show ownership and mode of a volume under /Volumes",
        sound=7,
        tags=("permissions", "volume", "nas"),
        body='ls -ld "/Volumes/$1"',
        prompts=(Prompt("", "Volume name", required=True),),
        macos_only=True,
    ),
    # -- drives -------------------------------------------------------------
    _cmd(
        name="mount-all-drives",
        flags=("--only", "--use-ip", "--quiet"),
        category="drives",
        icon="💿",
        summary="Mount all NAS drives over SMB via AppleScript",
        script="drives/mount-all-drives.py",
        sound=7,
        needs=("osascript",),
        macos_only=True,
        tags=("nas", "smb", "mount"),
        prompts=(Prompt("--only", "Only this drive", help="Case-insensitive name"),),
    ),
    _cmd(
        name="eject-all-drives",
        flags=("--dry-run", "--only", "--no-force", "--no-clear-favorites", "--quiet"),
        category="drives",
        icon="📤",
        summary="Eject all NAS volumes from /Volumes",
        script="drives/eject-all-drives.py",
        sound=7,
        dry_sound=7,
        dry_run="flag",
        destructive=True,
        needs=("diskutil",),
        macos_only=True,
        tags=("nas", "smb", "eject", "unmount"),
        prompts=(Prompt("--only", "Only this drive", help="Case-insensitive name"),),
    ),
    _cmd(
        name="ping-nas",
        flags=(
            "--interval",
            "--ping-timeout",
            "--only",
            "--no-remount",
            "--use-ip",
            "--once",
            "--quiet",
        ),
        category="drives",
        icon="📡",
        summary="Keep-alive pinger that remounts a NAS drive that dropped off",
        script="drives/ping-nas.py",
        macos_only=True,
        tags=("nas", "keepalive", "network"),
    ),
    # -- system -------------------------------------------------------------
    _cmd(
        name="update-brew",
        flags=("--dry-run", "--no-cask", "--no-cleanup"),
        category="system",
        icon="🍺",
        summary="Update Homebrew, upgrade formulae and casks, then clean up",
        script="system/update-brew.py",
        sound=7,
        dry_sound=7,
        dry_run="flag",
        needs=("brew",),
        tags=("homebrew", "update", "packages"),
        prompts=(
            Prompt("--no-cask", "Skip casks", kind="bool"),
            Prompt("--no-cleanup", "Skip brew cleanup", kind="bool"),
        ),
    ),
    _cmd(
        name="btop",
        flags=(),
        category="system",
        icon="📈",
        summary="Launch btop with a gruvbox theme matching the macOS appearance",
        script="system/btop-launch.py",
        needs=("btop",),
        tags=("monitor", "process", "cpu"),
    ),
)


# ---------------------------------------------------------------------------
# Built-in subcommands - handled inside che.py, listed here so they show up in
# `che --help`, the completions and the menu alongside everything else.
# ---------------------------------------------------------------------------

BUILTINS: tuple[Command, ...] = (
    _cmd(
        name="install",
        flags=(
            "--shells",
            "--all-shells",
            "--yes",
            "--dry-run",
            "--no-completions",
            "--no-path-shim",
            "--replace-legacy",
            "--print",
        ),
        category="che",
        icon="📥",
        summary="Install the shell wrappers into your shell startup files",
        builtin=True,
        tags=("setup", "wizard", "zshrc", "bashrc"),
    ),
    _cmd(
        name="update",
        flags=("--check", "--yes"),
        category="che",
        icon="⬆️",
        summary="Pull the latest scripts and refresh the installed wrappers",
        builtin=True,
        needs=("git",),
        tags=("upgrade", "self-update", "pull"),
    ),
    _cmd(
        name="doctor",
        flags=("--json", "--verbose"),
        category="che",
        icon="🩺",
        summary="Check the install, the interpreter and every external tool",
        builtin=True,
        tags=("diagnose", "health", "check"),
    ),
    _cmd(
        name="uninstall",
        flags=("--yes", "--dry-run", "--purge"),
        category="che",
        icon="🧽",
        summary="Remove the wrappers, the shim and the completions",
        builtin=True,
        tags=("remove", "clean"),
    ),
    _cmd(
        name="list",
        flags=("--category", "--json", "--dry"),
        category="che",
        icon="📋",
        summary="List every command, one per line",
        builtin=True,
        tags=("ls", "commands"),
    ),
    _cmd(
        name="completions",
        flags=("--shell"),
        category="che",
        icon="⌨️",
        summary="Print the completion script for a shell",
        builtin=True,
        tags=("tab", "complete"),
    ),
)

BUILTIN_NAMES = frozenset(command.name for command in BUILTINS)


# ---------------------------------------------------------------------------
# Menu keys
#
# Lives here rather than in che.py so the README can be generated from it: a
# keybinding documented in two hand-written places is a keybinding that will
# eventually be wrong in one of them.
# ---------------------------------------------------------------------------

MENU_KEYS: tuple[tuple[str, str], ...] = (
    ("↑ ↓ / j k", "move"),
    ("PgUp PgDn / g G", "jump"),
    ("⏎", "run (asks for arguments)"),
    ("x", "run with no arguments"),
    ("d", "toggle dry-run for this command"),
    ("h", "show the command's own --help"),
    ("/", "search, Esc to clear"),
    ("?", "this list"),
    ("q", "quit"),
)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Resolved:
    """A command name resolved to the command plus whether it was the ``-dr`` twin."""

    command: Command
    dry: bool = False
    matched: str = field(default="")


_BY_NAME: dict[str, Command] = {command.name: command for command in (*COMMANDS, *BUILTINS)}


def all_commands(*, include_builtins: bool = True) -> tuple[Command, ...]:
    return (*COMMANDS, *BUILTINS) if include_builtins else COMMANDS


def resolve(name: str) -> Resolved | None:
    """Look up ``name``, honouring the ``-dr`` preview suffix.

    ``resolve("delete-by-ext-dr")`` returns the ``delete-by-ext`` command with
    ``dry=True``. Returns ``None`` for anything unknown; callers turn that into
    a "did you mean" message rather than an exception, because the name usually
    came from a typo at a shell prompt.
    """
    command = _BY_NAME.get(name)
    if command is not None:
        return Resolved(command, dry=False, matched=name)

    if name.endswith(DRY_SUFFIX):
        base = _BY_NAME.get(name[: -len(DRY_SUFFIX)])
        if base is not None and base.has_dry_twin:
            return Resolved(base, dry=True, matched=name)

    return None


def wrapper_names() -> Iterator[str]:
    """Every name the generated shell files define, in menu order."""
    for command in COMMANDS:
        yield command.name
        if command.has_dry_twin:
            yield command.dry_name


def command_names(*, include_dry: bool = True, include_builtins: bool = True) -> list[str]:
    names = []
    for command in all_commands(include_builtins=include_builtins):
        names.append(command.name)
        if include_dry and command.has_dry_twin:
            names.append(command.dry_name)
    return names


def in_category(key: str) -> tuple[Command, ...]:
    return tuple(command for command in all_commands() if command.category == key)


def required_binaries() -> dict[str, tuple[str, ...]]:
    """Map each external binary to the commands that need it, sorted by name."""
    index: dict[str, list[str]] = {}
    for command in all_commands():
        for binary in command.needs:
            index.setdefault(binary, []).append(command.name)
    return {binary: tuple(names) for binary, names in sorted(index.items())}


def suggest(name: str, *, limit: int = 3) -> list[str]:
    """Closest known command names, for the "did you mean" line."""
    from difflib import get_close_matches

    pool = command_names()
    close = get_close_matches(name, pool, n=limit, cutoff=0.6)
    if close:
        return close
    # get_close_matches misses substring typos like "codecs" for "show-codecs".
    return [candidate for candidate in pool if name and name in candidate][:limit]


def fuzzy_match(query: str, command: Command) -> int | None:
    """Score ``command`` against ``query`` for the menu's type-to-filter.

    Returns ``None`` when it does not match at all, otherwise a score where
    lower is better: an exact name prefix beats a name substring, which beats a
    match that only landed in the summary or tags, which beats a subsequence
    match ("dbe" -> "delete-by-ext").
    """
    if not query:
        return 0

    needle = query.lower().strip()
    name = command.name.lower()

    if name.startswith(needle):
        return 1
    if needle in name:
        return 2
    if needle in command.search_text():
        return 3

    # Subsequence: every character of the query appears in order in the name.
    position = 0
    for char in needle:
        found = name.find(char, position)
        if found < 0:
            return None
        position = found + 1
    return 4
