#!/usr/bin/env python3
"""📉 Find (and optionally delete) video files at or under a size threshold.

Usage:
  files-under-size.py --path=/dir --size=1MB [--dry-run]

Options:
  --path=DIR    Directory to scan (required)
  --size=SIZE   Threshold, e.g. 500k / 1MB / 2GiB (required, binary units,
                bytes through gigabytes only)
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
    format_bytes,
    info,
    iter_files,
    log,
    note_settings,
    parse_size,
    run_cli,
    scan_root,
    warning,
)

__version__ = "3.0.0"

VIDEO_EXTENSIONS = (
    "mp4",
    "mkv",
    "avi",
    "mov",
    "flv",
    "wmv",
    "webm",
    "mpeg",
    "mpg",
    "m4v",
)


class Small(Outcome):
    """Everything deleting an undersized video can conclude, in summary order."""

    DELETED = (OK, "deleted", "Deleted")
    WOULD_DELETE = (PLAN, "would delete", "Would delete")
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="files-under-size",
        description="📉 Find video files at or under a size threshold.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    parser.add_argument("--size", default="", metavar="SIZE", help="Threshold, e.g. 1MB (required)")
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", True),
        help="List what would be deleted, change nothing",
    )

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)
    started = time.monotonic()

    note_settings(("Scanning", args.path), ("Size threshold", args.size), ("Dry run", args.dry_run))

    if not args.size or not args.path:
        warning("❌ --size and --path are required")
        warning("📋 Usage: files-under-size.py --path=/dir --size=1MB [--dry-run]")
        return 1

    try:
        limit_bytes = parse_size(args.size)
    except ValueError as exc:
        warning(f"❌ {exc}")
        return 1

    root = scan_root(args.path)

    # The shell version used `find -size -Nc` with N = limit + 1, which selects
    # files of AT MOST `limit` bytes. Keep the inclusive comparison.
    matches: list[tuple[Path, int]] = []
    for path in iter_files(root, extensions=VIDEO_EXTENSIONS, skip_macos_metadata=False):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= limit_bytes:
            matches.append((path, size))

    total = len(matches)
    info(f"Found {plural(total, 'file')} ≤ {args.size} ({limit_bytes:,} bytes)")

    tally = Tally(Small)
    freed = 0
    with tally.progress(total) as progress:
        for path, size in matches:
            progress.step(str(path))
            if args.dry_run:
                tally.record(Small.WOULD_DELETE, str(path), format_bytes(size))
                continue
            deleted = tally.attempt(
                path.unlink,
                str(path),
                done=Small.DELETED,
                failed=Small.FAILED,
                detail=format_bytes(size),
            )
            freed += size if deleted else 0

    notes = []
    if not total:
        notes.append(f"No matching video files ≤ {args.size} ({limit_bytes} bytes).")
    elif freed:
        notes.append(f"Freed {format_bytes(freed)}.")
    tally.summary(
        "Preview" if args.dry_run else "Summary",
        facts=[plural(total, "file"), duration(time.monotonic() - started)],
        notes=notes,
    )
    print()
    if count := tally.count(Small.FAILED):
        warning(
            f"⚠️  {plural(count, 'file')} could not be deleted. Every other file was still attempted."
        )
        return 1
    if args.dry_run:
        dry_run_complete("deleted")
    else:
        log("🎉 Done.")
    return 0


if __name__ == "__main__":
    run_cli(main)
