#!/usr/bin/env python3
"""🗑️  Delete every file under a path matching a set of extensions.

Usage:
  delete-by-ext.py --path=/dir [--ext=jpg,png,mp4] [--dry-run] [--verbose]

Options:
  --path=DIR    Directory to scan (required)
  --ext=LIST    Comma-separated extensions, no dots. Glob metacharacters work,
                so --ext=mp* matches mp4/mp3/mpg
                (default: m3u,nfo,sfv,jpg,png,txt,log,cue,srr)
  --dry-run     Print what would be deleted, change nothing
  --verbose     Extra detail
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
    normalize_extensions,
    note_settings,
    run_cli,
    scan_root,
    warning,
)

__version__ = "3.0.0"

DEFAULT_EXTENSIONS = ("m3u", "nfo", "sfv", "jpg", "png", "txt", "log", "cue", "srr")


class Delete(Outcome):
    """Everything deleting a matching file can conclude, in summary order."""

    DELETED = (OK, "deleted", "Deleted")
    WOULD_DELETE = (PLAN, "would delete", "Would delete")
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="delete-by-ext",
        description="🗑️  Delete files under a path matching a set of extensions.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    parser.add_argument(
        "--ext",
        default=",".join(DEFAULT_EXTENSIONS),
        metavar="LIST",
        help=f"Comma-separated extensions (default: {','.join(DEFAULT_EXTENSIONS)})",
    )
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", True),
        help="Print what would be deleted, change nothing",
    )
    add_bool_flag(parser, "--verbose", help="Extra detail")

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)
    started = time.monotonic()

    extensions = normalize_extensions(args.ext)

    note_settings(
        ("Scanning", args.path),
        ("Extensions", " ".join(extensions)),
        ("Dry run", args.dry_run),
        ("Verbose", args.verbose),
    )

    if not extensions:
        warning("--ext is required")
        return 1

    root = scan_root(args.path)

    tally = Tally(Delete)

    # macOS ._ sidecars are NOT skipped: the shell version deleted them when
    # they matched, and leaving them orphaned after their parent file is gone
    # is worse than deleting them.
    # No progress line: the walk streams, so there is no total to count against.
    for path in iter_files(root, extensions=extensions, skip_macos_metadata=False):
        if args.dry_run:
            tally.record(Delete.WOULD_DELETE, str(path))
            continue
        tally.attempt(path.unlink, str(path), done=Delete.DELETED, failed=Delete.FAILED)

    matched = tally.count(*Delete)
    tally.summary(
        "Preview" if args.dry_run else "Summary",
        facts=[plural(matched, "matching file"), duration(time.monotonic() - started)],
    )
    print()
    if count := tally.count(Delete.FAILED):
        warning(
            f"⚠️  {plural(count, 'file')} could not be deleted. Every other file was still attempted."
        )
        return 1
    if args.dry_run:
        dry_run_complete("deleted")
    else:
        log("🎉 Deletion complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
