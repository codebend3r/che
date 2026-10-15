#!/usr/bin/env python3
"""🧹 Delete truly-empty directories under a path, cascading upwards.

Only *strictly* empty directories are removed. A folder holding nothing but
``.DS_Store``, ``._*`` or ``.git`` is intentionally left alone - a recursive
delete would silently wipe them.

Usage:
  delete-empty-folders.py --path=/dir [--dry-run] [--verbose]

Options:
  --path=DIR    Directory to scan (required)
  --dry-run     Print what would be deleted, change nothing
  --verbose     Report skipped non-empty directories too
  --help        Show help

Env:
  DRY_RUN=false Opt out of the preview-only default (used by the generated wrapper)
"""

from __future__ import annotations

import os
import sys
from collections.abc import Container
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    env_bool,
    info,
    log,
    note,
    note_settings,
    remove_or_warn,
    report_walk_error,
    run_cli,
    scan_root,
)

__version__ = "3.1.0"


def directories_deepest_first(root: Path) -> list[Path]:
    """Every directory under ``root``, children before parents.

    This is ``find -depth -type d``. The ordering is what makes cascading work:
    emptying a leaf lets its parent become empty, and the parent is visited
    afterwards. The whole tree is enumerated up front - exactly like ``find``
    piping into a loop - and emptiness is re-checked at visit time, so a
    directory emptied earlier in the run is seen as empty when its turn comes.
    """
    walk = os.walk(root, topdown=False, followlinks=False, onerror=report_walk_error)
    return [Path(dirpath) for dirpath, _, _ in walk]


def is_strictly_empty(path: Path, gone: Container[Path]) -> bool:
    """True only when the directory has no entries at all, hidden included.

    Entries in ``gone`` do not count: they are the directories a dry run has
    already reported, which a real run would have removed by now.
    """
    try:
        return all(entry in gone for entry in path.iterdir())
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="delete-empty-folders",
        description="🧹 Delete truly-empty directories under a path, cascading upwards.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", True),
        help="Print what would be deleted, change nothing",
    )
    add_bool_flag(parser, "--verbose", help="Report skipped non-empty directories too")

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    # An empty --path reads "--path is required", where the shell version
    # printed "Error: --path is required.".
    root = scan_root(args.path)

    note_settings(
        ("Searching in", args.path),
        ("Dry run", args.dry_run),
        ("Verbose", args.verbose),
        rule=False,
    )

    # DELIBERATE DIVERGENCE: a dry run counts the directories it reports as
    # already gone, so `a/b/c` previews all three. The shell version (and
    # this one, until 3.1.0) re-checked the untouched filesystem and previewed
    # only the leaf, under-reporting what the real run then deleted.
    would_delete: set[Path] = set()
    deleted_count = 0
    failures = 0

    for directory in directories_deepest_first(root):
        if directory == root:
            continue  # never touch the root the user pointed at

        if not is_strictly_empty(directory, would_delete):
            if args.verbose:
                note(f"Skipped (not empty): {directory}")
            continue

        if args.dry_run:
            log(f"[DRY-RUN] Would delete: {directory}")
            would_delete.add(directory)
        else:
            if not remove_or_warn(directory, Path.rmdir):
                failures += 1
                continue
            log(f"Deleted: {directory}")
        deleted_count += 1

    log(f"📊 Total deleted directories: {deleted_count}")
    return 1 if failures else 0


if __name__ == "__main__":
    run_cli(main)
