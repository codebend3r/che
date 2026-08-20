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
    format_bytes,
    info,
    iter_files,
    log,
    note,
    parse_size,
    run_cli,
    scan_root,
    warning,
)

__version__ = "2.2.0"

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

    note(f"Scanning: {args.path}")
    note(f"Size threshold: {args.size}")
    note(f"Dry run: {str(args.dry_run).lower()}")
    note("----------------------------------------------------")

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
    if total == 0:
        log(f"No matching video files ≤ {args.size} ({limit_bytes} bytes).")
        return 0

    info(f"Found {total} file(s) ≤ {args.size} ({limit_bytes} bytes)")
    note(f"Threshold: {limit_bytes:,} bytes ({args.size})")

    failures = 0

    for index, (path, size) in enumerate(matches, start=1):
        log(f"File size: {format_bytes(size)}")
        if args.dry_run:
            warning(f"[{index}/{total}] Would delete: {format_bytes(size)} - {path}")
            continue

        warning(f"[{index}/{total}] Deleting: {format_bytes(size)} - {path}")
        try:
            path.unlink()
        except OSError as exc:
            # The shell version aborted the run here; reporting and continuing
            # means one busy file cannot strand the rest of the sweep.
            warning(f"  ✗ Failed to delete {path}: {exc}")
            failures += 1

    log("Done.")
    return 1 if failures else 0


if __name__ == "__main__":
    run_cli(main)
