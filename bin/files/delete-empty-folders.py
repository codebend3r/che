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
  DRY_RUN=false Opt out of the preview-only default (used by the .zshrc wrapper)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    env_bool,
    info,
    log,
    note,
    run_cli,
    scan_root,
    warning,
)

__version__ = "3.0.0"


def directories_deepest_first(root: Path) -> list[Path]:
    """Every directory under ``root``, children before parents.

    This is ``find -depth -type d``. The ordering is what makes cascading work:
    emptying a leaf lets its parent become empty, and the parent is visited
    afterwards. The whole tree is enumerated up front - exactly like ``find``
    piping into a loop - and emptiness is re-checked at visit time against the
    live filesystem, so a directory emptied earlier in the run is seen as
    empty when its turn comes.
    """

    def _on_error(exc: OSError) -> None:
        warning(f"find: {exc.filename}: {exc.strerror}")

    found: list[Path] = []
    for dirpath, _, _ in os.walk(root, topdown=False, followlinks=False, onerror=_on_error):
        found.append(Path(dirpath))
    return found


def is_strictly_empty(path: Path) -> bool:
    """True only when the directory has no entries at all, hidden included."""
    try:
        next(path.iterdir())
    except StopIteration:
        return True
    except OSError:
        return False
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

    if not args.path:
        warning("Error: --path is required.")
        return 1

    root = scan_root(args.path)

    note(f"Searching in: {args.path}")
    note(f"Dry run: {str(args.dry_run).lower()}")
    note(f"Verbose: {str(args.verbose).lower()}")

    # Compare resolved paths so `--path=foo` and `--path=foo/` protect the same
    # directory regardless of how it was spelled.
    root_resolved = root.resolve()
    deleted_count = 0
    failures = 0

    for directory in directories_deepest_first(root):
        if directory.resolve() == root_resolved:
            continue  # never touch the root the user pointed at

        if not is_strictly_empty(directory):
            if args.verbose:
                note(f"Skipped (not empty): {directory}")
            continue

        if args.dry_run:
            log(f"[DRY-RUN] Would delete: {directory}")
        else:
            try:
                directory.rmdir()
            except OSError as exc:
                # The shell version aborted here under `set -e`; reporting and
                # carrying on lets one unwritable directory not strand the rest.
                warning(f"  ✗ Failed to delete {directory}: {exc}")
                failures += 1
                continue
            log(f"Deleted: {directory}")
        deleted_count += 1

    log(f"📊 Total deleted directories: {deleted_count}")
    return 1 if failures else 0


if __name__ == "__main__":
    run_cli(main)
