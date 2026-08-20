#!/usr/bin/env python3
"""🧽 Delete the ``.smbdelete*`` turds an SMB share leaves behind.

Usage:
  delete-smb-files.py --path=/dir [--dry-run]

Options:
  --path=DIR    Directory to scan (required)
  --dry-run     List what would be deleted, change nothing
  --help        Show help

Env:
  DRY_RUN=false Opt out of the preview-only default (used by the .zshrc wrapper)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    env_bool,
    info,
    iter_files,
    log,
    note,
    run_cli,
    scan_root,
    warning,
)

__version__ = "2.1.0"

PREFIX = ".smbdelete"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="delete-smb-files",
        description="🧽 Delete .smbdelete* files left behind by an SMB share.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", True),
        help="List what would be deleted, change nothing",
    )

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    note(f"Searching in: {args.path}")
    note(f"Dry run: {str(args.dry_run).lower()}")

    if not args.path:
        warning("Error: --path is required.")
        warning("Usage: delete-smb-files.py --path=/directory/to/scan")
        return 1

    root = scan_root(args.path)

    info(f"Scanning for .smbdelete* files under: {args.path}")

    if args.dry_run:
        info("Dry run mode: no files will be deleted.")

    deleted = 0
    failures = 0

    # These sidecars are hidden files, so hidden entries must NOT be skipped.
    # `._*` filtering is likewise off - a `._.smbdeleteX` is still junk.
    for path in iter_files(root, skip_macos_metadata=False):
        if not path.name.startswith(PREFIX):
            continue

        print(path, flush=True)
        if args.dry_run:
            continue

        try:
            path.unlink()
        except OSError as exc:
            # A file held open by the SMB client fails with "Resource busy".
            # The shell version swallowed these with `2>/dev/null || true`;
            # naming them is strictly more useful and still non-fatal.
            warning(f"  ✗ Could not delete {path}: {exc}")
            failures += 1
            continue
        deleted += 1

    if not args.dry_run:
        # Summary line the shell version did not print; a sweep that silently
        # deleted nothing is indistinguishable from one that could not run.
        log(f"📊 Deleted {deleted} file(s).")

    return 1 if failures else 0


if __name__ == "__main__":
    run_cli(main)
