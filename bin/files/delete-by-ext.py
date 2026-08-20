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
    normalize_extensions,
    note,
    run_cli,
    scan_root,
    warning,
)

__version__ = "2.2.0"

DEFAULT_EXTENSIONS = ("m3u", "nfo", "sfv", "jpg", "png", "txt", "log", "cue", "srr")


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

    extensions = normalize_extensions(args.ext)

    note(f"Scanning: {args.path}")
    note(f"Extensions: {' '.join(extensions)}")
    note(f"Dry run: {str(args.dry_run).lower()}")
    note(f"Verbose: {str(args.verbose).lower()}")
    note("----------------------------------------------------")

    if not extensions:
        warning("--ext is required")
        return 1

    root = scan_root(args.path)

    failures = 0

    # macOS ._ sidecars are NOT skipped: the shell version deleted them when
    # they matched, and leaving them orphaned after their parent file is gone
    # is worse than deleting them.
    for path in iter_files(root, extensions=extensions, skip_macos_metadata=False):
        if args.dry_run:
            info(f"[DRY RUN] Would delete: {path}")
            continue

        log(f"Deleting: {path}")
        try:
            path.unlink()
        except OSError as exc:
            # The shell version aborted the whole run here under `set -e`.
            # Continuing and reporting at the end is more useful on a NAS
            # where one busy file should not strand the rest of the sweep.
            warning(f"  ✗ Failed to delete {path}: {exc}")
            failures += 1

    log("Completed.")
    return 1 if failures else 0


if __name__ == "__main__":
    run_cli(main)
