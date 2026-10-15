#!/usr/bin/env python3
"""📺 Rank TV show folders in a library by total size on disk.

A TV show folder is any folder with at least one direct child folder named
``Season <N>``.

Usage:
  largest-tv-shows.py --path=/path/to/tv [--limit=20] [--full-path] [--debug]

Options:
  --path=DIR     TV library root (required)
  --limit=N      How many shows to list (default: 20)
  --full-path    Print the whole path instead of just the show name
  --debug        Print traversal detail
  --help         Show help
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    format_bytes,
    info,
    note,
    note_settings,
    parse_count,
    run_cli,
    scan_root,
    warning,
)

__version__ = "3.1.0"

# `^Season[[:space:]]+[0-9]+$` in the shell version. \Z rather than $ because $
# also matches before a trailing newline, and an explicit [ \t] rather than \s
# because Python's \s and \d are Unicode-aware - a non-ASCII digit would
# otherwise match where the shell version's POSIX classes did not.
SEASON_RE = re.compile(r"Season[ \t]+[0-9]+\Z")


def _silent(_message: str) -> None:
    """The ``trace`` used without ``--debug``."""


def is_tv_show_folder(
    path: Path, child_dirs: list[str], *, trace: Callable[[str], None] = _silent
) -> bool:
    """True when one of ``child_dirs``, the folders directly in ``path``, is ``Season <N>``.

    ``child_dirs`` is the listing ``os.walk`` already made, so a folder is
    read once. Taken in its sorted order, which only shows in ``trace``.
    """
    trace(f"[DEBUG] Checking folder: {path}")
    for name in child_dirs:
        # os.walk lists a symlinked folder without descending into it. find
        # -type d does not match a symlink; following one here would report a
        # show whose season folder lives elsewhere, and then size it at zero
        # because the walk below refuses to descend.
        if (path / name).is_symlink():
            continue
        trace(f"[DEBUG]   Found child folder: {name}")
        if SEASON_RE.fullmatch(name):
            trace(f"[DEBUG]   Matched season folder in: {path}")
            return True
    trace(f"[DEBUG]   No season folders found in: {path}")
    return False


def folder_size(path: Path) -> int:
    """Disk usage under ``path``, matching ``du -sk`` closely enough to rank by.

    ``st_blocks * 512`` is ALLOCATED size, which is what ``du`` reports - not
    ``st_size``, which is the apparent size. The difference is not cosmetic
    here: a sparse preallocated download reads as its full final size, and a
    library of many small files reads far under its real footprint.

    A hard-linked file is counted once, again matching ``du``. Sonarr and
    Radarr hardlink into the library while seeding, so without this a show
    holding both copies would double. The de-duplication is per-show, because
    the shell version ran one ``du -sk`` per show and each invocation
    de-duplicates only within its own tree.
    """
    seen: set[tuple[int, int]] = set()
    total = 0
    for dirpath, _, filenames in os.walk(path, followlinks=False):
        for name in filenames:
            try:
                stat = (Path(dirpath) / name).lstat()
            except OSError:
                continue
            if stat.st_nlink > 1:
                key = (stat.st_dev, stat.st_ino)
                if key in seen:
                    continue
                seen.add(key)
            total += stat.st_blocks * 512
    return total


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="largest-tv-shows",
        description="📺 Rank TV show folders in a library by total size on disk.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="TV library root (required)")
    # Kept as a string and checked by parse_count, so "+5" is rejected the way
    # the shell version's ^[0-9]+$ test rejected it, not accepted by int().
    parser.add_argument("--limit", default="20", metavar="N", help="How many to list")
    add_bool_flag(parser, "--full-path", help="Print the whole path")
    add_bool_flag(parser, "--debug", help="Print traversal detail")

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    note_settings(
        ("Searching in", args.path),
        ("Limit", args.limit),
        ("Show full path", args.full_path),
        ("Debug", args.debug),
        rule=False,
    )

    # An empty --path reads "--path is required", where the shell version
    # printed a one-line usage.
    root = scan_root(args.path)

    # Same test as the shell version's ^[0-9]+$ and -lt 1. The message is the
    # repo-wide parse_count one, which also echoes the rejected value.
    limit = parse_count(args.limit, "--limit", minimum=1)

    note("Scanning for TV show folders...")

    trace = note if args.debug else _silent
    shows: list[tuple[int, Path]] = []

    # Nested show folders are listed too (a "Doctor Who Confidential" inside
    # "Doctor Who" is its own row), matching the shell version. Its bytes still
    # count toward the parent as well - that is how `du -s` on the parent works.
    for dirpath, dirnames, _ in os.walk(root, followlinks=False):
        dirnames.sort()
        directory = Path(dirpath)
        trace(f"[DEBUG] Scanning candidate: {directory}")
        if not is_tv_show_folder(directory, dirnames, trace=trace):
            continue
        size = folder_size(directory)
        shows.append((size, directory))
        trace(f"[DEBUG] Detected TV show folder: {directory.name} | Size: {size}")

    info(f"Detected {len(shows)} TV show folder(s)")

    if not shows:
        warning("No TV show folders found.")
        return 0

    # `sort -rn` reverses the whole comparison, including its last-resort
    # tiebreak on the full line - so equal-sized shows come out in DESCENDING
    # name order. Reversing both key fields reproduces that.
    shows.sort(key=lambda item: (item[0], item[1].name), reverse=True)

    note(f"Top {limit} largest TV show folders:")
    for size, path in shows[:limit]:
        label = str(path) if args.full_path else path.name
        print(f"{format_bytes(size):<12} {label}", flush=True)

    return 0


if __name__ == "__main__":
    run_cli(main)
