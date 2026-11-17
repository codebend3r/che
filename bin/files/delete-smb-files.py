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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from report import FAIL, OK, PLAN, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    dry_run_complete,
    env_bool,
    info,
    iter_files,
    log,
    note_settings,
    run_cli,
    scan_root,
    warning,
)

__version__ = "3.0.0"

PREFIX = ".smbdelete"


class Sweep(Outcome):
    """Everything deleting a placeholder can conclude, in summary order."""

    DELETED = (OK, "deleted", "Deleted")
    WOULD_DELETE = (PLAN, "would delete", "Would delete")
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


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
    started = time.monotonic()

    note_settings(("Searching in", args.path), ("Dry run", args.dry_run), rule=False)

    # An empty --path reads "--path is required", where the shell version
    # printed "Error: --path is required." and a usage line.
    root = scan_root(args.path)

    info(f"Scanning for .smbdelete* files under: {args.path}")

    if args.dry_run:
        info("Dry run mode: no files will be deleted.")

    tally = Tally(Sweep)

    # Case-sensitive prefix, as `find -name '.smbdelete*'` matched. That never
    # reached a `._.smbdelete*` AppleDouble sidecar, and neither does this.
    # No progress line: the walk streams, so there is no total to count against.
    for path in iter_files(root):
        if not path.name.startswith(PREFIX):
            continue

        if args.dry_run:
            tally.record(Sweep.WOULD_DELETE, str(path))
            continue

        # A file held open by the SMB client fails with "Resource busy".
        try:
            path.unlink()
        except OSError as exc:
            reason = exc.strerror or str(exc)
            tally.record(Sweep.FAILED, str(path), reason, item=f"{path}: {reason}")
            continue
        tally.record(Sweep.DELETED, str(path))

    # A closing summary the shell version did not print; a sweep that silently
    # deleted nothing is indistinguishable from one that could not run.
    tally.summary(
        "Preview" if args.dry_run else "Summary",
        facts=[plural(tally.count(*Sweep), "placeholder"), duration(time.monotonic() - started)],
    )
    print()
    if count := tally.count(Sweep.FAILED):
        warning(
            f"⚠️  {plural(count, 'file')} could not be deleted. Every other file was still attempted."
        )
        return 1
    if args.dry_run:
        dry_run_complete("deleted")
    else:
        log("🎉 Sweep complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
