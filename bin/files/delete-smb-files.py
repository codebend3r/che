#!/usr/bin/env python3
"""🧽 Delete the ``.smbdelete*`` turds an SMB share leaves behind.

Usage:
  delete-smb-files.py --path=/dir [--dry-run]

Options:
  --path=DIR    Directory to scan (required)
  --dry-run     List what would be deleted, change nothing
  --help        Show help

Env:
  DRY_RUN=false Opt out of the preview-only default (used by the generated wrapper)
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
    note_settings,
    remove_or_warn,
    run_cli,
    scan_root,
)

__version__ = "2.1.1"

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

    note_settings(("Searching in", args.path), ("Dry run", args.dry_run), rule=False)

    # An empty --path reads "--path is required", where the shell version
    # printed "Error: --path is required." and a usage line.
    root = scan_root(args.path)

    info(f"Scanning for .smbdelete* files under: {args.path}")

    if args.dry_run:
        info("Dry run mode: no files will be deleted.")

    deleted = 0
    failures = 0

    # Case-sensitive prefix, as `find -name '.smbdelete*'` matched. That never
    # reached a `._.smbdelete*` AppleDouble sidecar, and neither does this.
    for path in iter_files(root):
        if not path.name.startswith(PREFIX):
            continue

        print(path, flush=True)
        if args.dry_run:
            continue

        # A file held open by the SMB client fails with "Resource busy".
        if not remove_or_warn(path):
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
