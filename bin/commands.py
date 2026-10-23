"""Canonical registry of every command ``che`` exposes.

This module is the single source of truth for the user-facing command surface.
Four things are generated from it, so they can never drift apart:

* the shell wrappers in ``shell/che.zsh``, ``shell/che.bash`` and
  ``shell/che.fish`` (rendered by ``bin/shellgen.py``),
* the tab completions under ``shell/completions/``,
* the interactive menu in ``bin/menu.py``,
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

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# How a command previews: "" (it cannot), "env" (DRY_RUN=) or "flag" (--dry-run).
DryRunStyle = Literal["", "env", "flag"]

BIN = Path(__file__).resolve().parent
REPO = BIN.parent

# Version of the `che` app itself - the dispatcher, the installer and the
# generated shell files together. It is read from package.json so that one
# `npm version` bump moves the npm release, `che --version` and the header of
# every generated file at once. `che doctor` compares it against the version
# `che install` recorded in ~/.config/che/config.json to decide whether a
# re-install is needed.
_PACKAGE = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
PACKAGE_NAME: str = _PACKAGE["name"]
VERSION: str = _PACKAGE["version"]

# Suffix appended to a command name to get its preview-only twin.
DRY_SUFFIX = "-dr"


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    blurb: str


CATEGORIES: tuple[Category, ...] = (
    Category("git", "Git", "Branch hygiene, worktrees and GitHub Actions"),
    Category("video", "Video", "Codecs, renaming, dedupe and metadata"),
    Category("files", "Files", "Delete, compress and inspect by size or extension"),
    Category("drives", "Drives", "Mount, eject and keep-alive for the NAS volumes"),
    Category("system", "System", "Homebrew, monitoring and the machine itself"),
    Category("che", "che", "Install, update and inspect che itself"),
)


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

    flag: str  # "--path", without the "="; empty string means a positional argument
    label: str
    # "path" completes filenames and expands ~; "bool" asks yes/no and passes
    # the bare flag. Everything else is "text", re-asked until it is one of
    # `choices` when there are any.
    kind: Literal["text", "path", "bool"] = "text"
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


@dataclass(frozen=True, kw_only=True)
class Command:
    """One user-facing command: a name, a script and how to invoke it."""

    name: str
    category: str
    summary: str
    script: str = ""  # relative to bin/; empty only for a built-in
    icon: str = "•"
    sound: int | None = None
    dry_sound: int | None = 7
    args: tuple[str, ...] = ()  # fixed arguments, always passed first
    # Every flag the script accepts, for completions. One that takes a value is
    # spelled with its "=" ("--path="), the way it is typed.
    flags: tuple[str, ...] = ()
    prompts: tuple[Prompt, ...] = ()
    needs: tuple[str, ...] = ()  # external binaries the script shells out to
    dry_run: DryRunStyle = ""
    destructive: bool = False
    # Set only where a destructive command genuinely cannot preview, with the
    # reason. The menu shows it, and the manifest test demands one rather than
    # letting a missing dry-run pass unnoticed.
    no_preview_reason: str = ""
    # One-off setup a command needs that `needs` cannot express, because it is
    # not a binary on PATH (a venv, a credential, a mounted volume).
    setup: str = ""
    macos_only: bool = False
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # `flags=("--path")` is a string, not a tuple, and everything that
        # iterates it then offers `-`, `-`, `p`, `a`, `t`, `h` as flags.
        for name in ("args", "flags", "prompts", "needs", "tags"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                raise TypeError(f"{self.name}: {name} must be a tuple, got {value!r}")

    @property
    def builtin(self) -> bool:
        """Handled by che.py itself rather than by a script."""
        return self.name in BUILTIN_NAMES

    @property
    def has_dry_twin(self) -> bool:
        """Whether a ``-dr`` wrapper is generated alongside this command."""
        return bool(self.dry_run)

    @property
    def dry_name(self) -> str:
        return f"{self.name}{DRY_SUFFIX}"

    @property
    def flag_names(self) -> tuple[str, ...]:
        """``flags`` without the "=" that marks a flag taking a value."""
        return tuple(flag.removesuffix("=") for flag in self.flags)

    @property
    def preview(self) -> str:
        """How to look before running for real: the ``-dr`` twin, ``--dry-run``, or ""."""
        if self.has_dry_twin:
            return self.dry_name
        return "--dry-run" if "--dry-run" in self.flags else ""

    @property
    def path(self) -> Path:
        return BIN / self.script

    def variants(self) -> tuple[Resolved, ...]:
        """This command, then its ``-dr`` preview twin when it has one."""
        plain = Resolved(self)
        return (plain, Resolved(self, dry=True)) if self.has_dry_twin else (plain,)


COMMANDS: tuple[Command, ...] = (
    # -- git ----------------------------------------------------------------
    Command(
        name="all-actions",
        flags=(
            "--owner=",
            "--author=",
            "--pr-limit=",
            "--repo-limit=",
            "--no-main",
            "--interval=",
            "--watch",
        ),
        category="git",
        icon="🎬",
        summary="GitHub Actions status for every open PR and every default branch",
        script="git/all-actions.py",
        needs=("gh", "git"),
        tags=("ci", "pr", "github", "workflow", "main"),
        prompts=(
            Prompt("--owner", "Only this owner", help="Defaults to every repo you own"),
            Prompt("--pr-limit", "PRs per repo"),
            Prompt("--no-main", "Skip the default-branch table", kind="bool"),
        ),
    ),
    Command(
        name="all-actions-watch",
        flags=("--owner=", "--author=", "--pr-limit=", "--repo-limit=", "--no-main", "--interval="),
        category="git",
        icon="👀",
        summary="Same as all-actions, refreshed on an interval",
        script="git/all-actions.py",
        args=("--watch",),
        needs=("gh", "git"),
        tags=("ci", "pr", "github", "watch"),
    ),
    Command(
        name="checkout-my-branches",
        flags=("--author=", "--limit="),
        category="git",
        icon="🌿",
        summary="Check out recent remote branches you authored that aren't local yet",
        script="git/checkout-my-branches.py",
        sound=7,
        needs=("git",),
        tags=("branch", "remote"),
        prompts=(
            Prompt("--author", "Author email", help="Defaults to git config user.email"),
            Prompt("--limit", "Remote branches to scan"),
        ),
    ),
    Command(
        name="clean-stale-branches",
        flags=("--dry-run", "--protect="),
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
    Command(
        name="hard-reset-all-branches",
        flags=("--dry-run", "--force"),
        category="git",
        icon="💣",
        summary="Check out every local branch and hard reset it to origin/<branch>",
        script="git/hard-reset-all-branches.py",
        sound=4,
        dry_run="env",
        destructive=True,
        needs=("git",),
        tags=("branch", "reset", "origin", "worktree"),
        prompts=(Prompt("--force", "Also discard uncommitted changes", kind="bool"),),
    ),
    Command(
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
    Command(
        name="sync-all-branches",
        flags=("--dry-run", "--author=", "--limit="),
        category="git",
        icon="🔄",
        summary="Update every branch and worktree, pruning what has been merged",
        script="git/sync-all-branches.py",
        sound=7,
        dry_run="env",
        destructive=True,
        needs=("git",),
        tags=("branch", "sync", "pull", "worktree"),
    ),
    Command(
        name="update-from-origin",
        flags=("--dry-run", "--author=", "--limit="),
        category="git",
        icon="⬇️",
        summary="Alias of sync-all-branches",
        script="git/sync-all-branches.py",
        # A real run by default; a `--dry-run` typed after it still wins.
        args=("--dry-run=false",),
        sound=7,
        destructive=True,
        needs=("git",),
        tags=("pull", "fetch", "sync"),
    ),
    Command(
        name="update-local-branches",
        flags=("--limit=", "--dry-run"),
        category="git",
        icon="⬆️",
        summary="Rebase every local branch that has an upstream onto origin",
        script="git/update-local-branches.py",
        sound=5,
        needs=("git",),
        tags=("rebase", "branch"),
        prompts=(
            Prompt("--limit", "Only the N most recent branches"),
            DRY_PROMPT,
        ),
    ),
    # -- video --------------------------------------------------------------
    Command(
        name="show-codecs",
        flags=("--path=", "--verbose"),
        category="video",
        icon="🎥",
        summary="Report media files outside the Direct Play codec/container set",
        script="video/show-codecs.py",
        sound=6,
        needs=("ffprobe",),
        tags=("plex", "codec", "audit"),
        prompts=(PATH_PROMPT, Prompt("--verbose", "Also print files that pass", kind="bool")),
    ),
    Command(
        name="fix-codecs",
        flags=("--path=", "--delete-original", "--dry-run"),
        category="video",
        icon="🔧",
        summary="Re-encode media to h265/aac mp4 so it Direct Plays",
        script="video/fix-codecs.py",
        sound=7,
        dry_run="env",
        destructive=True,
        needs=("ffmpeg",),
        tags=("plex", "encode", "transcode"),
        prompts=(
            PATH_PROMPT,
            Prompt("--delete-original", "Delete each source after converting", kind="bool"),
        ),
    ),
    Command(
        name="find-video-mkv-issues",
        flags=("--path=", "--recursive"),
        category="video",
        icon="🎬",
        summary="Scan MKV files and estimate Plex direct-play compatibility",
        script="video/find-video-mkv-issues.py",
        sound=4,
        needs=("ffprobe",),
        tags=("plex", "mkv", "audit"),
        prompts=(PATH_PROMPT, Prompt("--recursive", "Recurse into subfolders", kind="bool")),
    ),
    Command(
        name="validate-video-files",
        flags=("--path=", "--verbose"),
        category="video",
        icon="🩺",
        summary="Check .mp4/.mkv files decode by playing one frame with mpv",
        script="video/validate-video-files.py",
        sound=2,
        needs=("mpv",),
        tags=("corrupt", "health", "audit"),
        prompts=(PATH_PROMPT, Prompt("--verbose", "Print each file as it is checked", kind="bool")),
    ),
    Command(
        name="scan-videos-audio-language",
        flags=("--path=",),
        category="video",
        icon="🔊",
        summary="Print the audio language tags of every video under a path",
        script="video/scan-videos-audio-language.py",
        sound=3,
        needs=("ffprobe",),
        tags=("audio", "language", "dub"),
        prompts=(PATH_PROMPT,),
    ),
    Command(
        name="remove-metadata",
        flags=("--path=", "--exts="),
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
    Command(
        name="rename-video-file",
        flags=(
            "--path=",
            "--recursive",
            "--rename-folders",
            "--capitalize-preps",
            "--dry-run",
            "--ignore-words=",
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
            Prompt("--rename-folders", "Rename folders too", kind="bool", default="true"),
            Prompt("--dry-run", "Preview only", kind="bool", default="true"),
            Prompt("--ignore-words", "Words to leave as written", help="Comma separated"),
        ),
    ),
    Command(
        name="delete-duplicate-videos",
        flags=("--path=", "--strategy=", "--dry-run", "--verbose"),
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
                choices=("episode", "filename", "size", "hash", "all"),
                default="episode",
            ),
        ),
    ),
    Command(
        name="video-list",
        flags=("--path=", "--recursive", "--with-folder", "--sort="),
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
                choices=("alpha", "fileSizeAsc", "fileSizeDesc"),
                default="alpha",
            ),
        ),
    ),
    Command(
        name="detect-green-magenta-videos",
        flags=("--samples=", "--threshold=", "--verbose"),
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
    Command(
        name="find-movie-by-year",
        flags=("--year=", "--path="),
        category="video",
        icon="🎞️",
        summary='Find movie folders whose name ends with "(YYYY)"',
        script="video/find-movie-by-year.py",
        sound=2,
        tags=("movie", "year", "search"),
        prompts=(Prompt("--year", "Year", required=True), PATH_PROMPT_CWD),
    ),
    Command(
        name="largest-tv-shows",
        flags=("--path=", "--limit=", "--full-path", "--debug"),
        category="video",
        icon="📺",
        summary="Rank TV show folders in a library by total size on disk",
        script="video/largest-tv-shows.py",
        sound=2,
        tags=("size", "tv", "report"),
        prompts=(PATH_PROMPT, Prompt("--limit", "How many to list", default="20")),
    ),
    # -- files --------------------------------------------------------------
    Command(
        name="delete-by-ext",
        flags=("--path=", "--ext=", "--dry-run", "--verbose"),
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
    Command(
        name="delete-empty-folders",
        flags=("--path=", "--dry-run", "--verbose"),
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
    Command(
        name="delete-smb-files",
        flags=("--path=", "--dry-run"),
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
    Command(
        name="files-under-size",
        flags=("--path=", "--size=", "--dry-run"),
        category="files",
        icon="📉",
        summary="Find video files at or under a size threshold",
        script="files/files-under-size.py",
        sound=4,
        dry_run="env",
        destructive=True,
        tags=("size", "delete", "small"),
        prompts=(PATH_PROMPT, Prompt("--size", "Size threshold", required=True)),
    ),
    Command(
        name="find-largest-files",
        flags=("--path=", "--length=", "--full-path"),
        category="files",
        icon="📊",
        summary="List the largest files under a path, biggest first",
        script="files/find-largest-files.py",
        sound=2,
        tags=("size", "report", "disk"),
        prompts=(
            PATH_PROMPT_CWD,
            Prompt("--length", "How many to list", default="10"),
            Prompt("--full-path", "Print the whole path", kind="bool"),
        ),
    ),
    Command(
        name="make-alpha-dir",
        flags=("--path=",),
        category="files",
        icon="🔤",
        summary="Create '#' and A-Z bucket folders under a parent directory",
        script="files/make-alpha-dir.py",
        sound=4,
        tags=("organize", "folders"),
        prompts=(PATH_PROMPT_CWD,),
    ),
    Command(
        name="compress-folders",
        flags=("--path=", "--dry-run", "--verbose"),
        category="files",
        icon="📦",
        summary="Zip every immediate subfolder of a path at max compression",
        script="files/compress-folders.py",
        sound=7,
        tags=("zip", "archive", "compress"),
        prompts=(PATH_PROMPT, DRY_PROMPT),
    ),
    Command(
        name="list-permission",
        flags=(),
        category="files",
        icon="🔐",
        summary="Show ownership and mode of a volume under /Volumes",
        script="files/list-permission.py",
        sound=7,
        tags=("permissions", "volume", "nas"),
        prompts=(Prompt("", "Volume name", required=True),),
        macos_only=True,
    ),
    # -- drives -------------------------------------------------------------
    Command(
        name="mount-all-drives",
        flags=("--only=", "--use-ip", "--quiet"),
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
    Command(
        name="eject-all-drives",
        flags=("--dry-run", "--only=", "--no-force", "--no-clear-favorites", "--quiet"),
        category="drives",
        icon="📤",
        summary="Eject all NAS volumes from /Volumes",
        script="drives/eject-all-drives.py",
        sound=7,
        dry_run="flag",
        destructive=True,
        needs=("diskutil",),
        macos_only=True,
        tags=("nas", "smb", "eject", "unmount"),
        prompts=(Prompt("--only", "Only this drive", help="Case-insensitive name"),),
    ),
    Command(
        name="ping-nas",
        flags=(
            "--interval=",
            "--ping-timeout=",
            "--only=",
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
    Command(
        name="update-brew",
        flags=("--dry-run", "--no-cask", "--no-cleanup", "--no-autoremove", "--greedy", "--doctor"),
        category="system",
        icon="🍺",
        summary="Update Homebrew, upgrade formulae and casks, then clean up",
        script="system/update-brew.py",
        sound=7,
        dry_run="flag",
        needs=("brew",),
        tags=("homebrew", "update", "packages"),
        prompts=(
            Prompt("--no-cask", "Skip casks", kind="bool"),
            Prompt("--no-cleanup", "Skip brew cleanup", kind="bool"),
        ),
    ),
    Command(
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
# `che --help`, the completions and the menu alongside everything else. Their
# flags are checked against each one's parser, like a script's against its
# --help.
# ---------------------------------------------------------------------------

BUILTINS: tuple[Command, ...] = (
    Command(
        name="install",
        flags=(
            "--shells=",
            "--all-shells",
            "--yes",
            "--dry-run",
            "--no-path-shim",
            "--no-sounds",
            "--replace-legacy",
            "--install-deps",
            "--print",
        ),
        category="che",
        icon="📥",
        summary="Install the shell wrappers into your shell startup files",
        tags=("setup", "wizard", "zshrc", "bashrc"),
    ),
    Command(
        name="update",
        flags=("--check", "--dry-run"),
        category="che",
        icon="⬆️",
        summary="Pull the latest scripts and refresh the installed wrappers",
        needs=("git",),
        tags=("upgrade", "self-update", "pull"),
    ),
    Command(
        name="doctor",
        flags=("--json", "--verbose"),
        category="che",
        icon="🩺",
        summary="Check the install, the interpreter and every external tool",
        tags=("diagnose", "health", "check"),
    ),
    Command(
        name="uninstall",
        flags=("--dry-run", "--purge"),
        category="che",
        icon="🧽",
        summary="Remove the wrappers, the shim and the completions",
        destructive=True,
        tags=("remove", "clean"),
        prompts=(
            Prompt("--dry-run", "Preview only", kind="bool", default="true"),
            Prompt("--purge", "Also delete the config and menu history", kind="bool"),
        ),
    ),
    Command(
        name="list",
        flags=("--category=", "--json", "--no-dry"),
        category="che",
        icon="📋",
        summary="List every command, one per line",
        tags=("ls", "commands"),
    ),
    Command(
        name="completions",
        flags=("--shell=",),
        category="che",
        icon="⌨️",
        summary="Print the completion script for a shell",
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
    """One name a user can call: a command, or its ``-dr`` preview twin."""

    command: Command
    dry: bool = False

    @property
    def name(self) -> str:
        return self.command.dry_name if self.dry else self.command.name

    @property
    def sound(self) -> int | None:
        return self.command.dry_sound if self.dry else self.command.sound

    def summary(self, preview: str) -> str:
        """The command's summary, with ``(preview)`` appended on the twin."""
        return f"{self.command.summary} ({preview})" if self.dry else self.command.summary

    @property
    def env(self) -> dict[str, str]:
        """Environment overrides under this name: ``DRY_RUN`` for a command
        that previews through it, nothing for any other."""
        if self.command.dry_run != "env":
            return {}
        return {"DRY_RUN": "true" if self.dry else "false"}

    @property
    def args(self) -> tuple[str, ...]:
        """Fixed arguments under this name, before anything the user typed: the
        command's own, plus ``--dry-run`` on the twin of a command that previews
        through the flag."""
        preview = ("--dry-run",) if self.dry and self.command.dry_run == "flag" else ()
        return (*self.command.args, *preview)


def all_commands() -> tuple[Command, ...]:
    return (*COMMANDS, *BUILTINS)


def variants(commands: Iterable[Command]) -> list[Resolved]:
    """Every callable name ``commands`` define, each twin right after its command."""
    return [variant for command in commands for variant in command.variants()]


def grouped(commands: Iterable[Command]) -> list[tuple[Category, list[Command]]]:
    """``commands`` by category, in category order, leaving out empty categories."""
    commands = tuple(commands)
    groups = [(cat, [c for c in commands if c.category == cat.key]) for cat in CATEGORIES]
    return [(category, members) for category, members in groups if members]


_BY_NAME: dict[str, Resolved] = {variant.name: variant for variant in variants(all_commands())}


def resolve(name: str) -> Resolved | None:
    """Look up ``name``, honouring the ``-dr`` preview suffix.

    ``resolve("delete-by-ext-dr")`` returns the ``delete-by-ext`` command with
    ``dry=True``. Returns ``None`` for anything unknown; callers turn that into
    a "did you mean" message rather than an exception, because the name usually
    came from a typo at a shell prompt.
    """
    return _BY_NAME.get(name)


def wrapper_names() -> list[str]:
    """Every name the generated shell files define, in menu order."""
    return [variant.name for variant in variants(COMMANDS)]


def command_names() -> list[str]:
    """Every name ``che`` accepts, the built-ins and the ``-dr`` twins included."""
    return list(_BY_NAME)


def required_binaries() -> dict[str, tuple[str, ...]]:
    """Map each external binary to the commands that need it, sorted by name."""
    index: dict[str, list[str]] = {}
    for command in all_commands():
        for binary in command.needs:
            index.setdefault(binary, []).append(command.name)
    return {binary: tuple(names) for binary, names in sorted(index.items())}
