#!/usr/bin/env python3
"""🔧 Re-encode media to h265/aac mp4 so it Direct Plays.

Usage:
  fix-codecs.py --path=/path/to/media [--delete-original] [--dry-run]

Options:
  --path=DIR           Directory to scan (required)
  --delete-original    Delete each source file after a successful convert
  --dry-run            Print what would be converted, change nothing
  --help               Show help

Defaults: --delete-original=false, --dry-run=true

Env:
  DRY_RUN=false        Opt out of the preview-only default
"""

from __future__ import annotations

import os
import subprocess
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
    require_binary,
    run,
    run_cli,
    scan_root,
    success,
    warning,
)

__version__ = "3.0.0"

SCAN_EXTENSIONS = ("mp4", "mkv", "mov", "avi")

FFMPEG_ARGS = (
    "-map",
    "0:v:0",
    "-map",
    "0:a:0",
    "-map",
    "0:s:0?",
    "-c:v",
    "libx265",
    "-preset",
    "slow",
    "-crf",
    "22",
    "-c:a",
    "aac",
    "-b:a",
    "384k",
    "-c:s",
    "mov_text",
    "-movflags",
    "+faststart",
    "-max_muxing_queue_size",
    "9999",
)


def encode(source: Path, output: Path) -> bool:
    """Encode ``source`` to ``output``. True on success.

    Written to a unique temp sibling and moved into place only on success, so
    a failed run can never delete anything but its own partial output. The
    shell version wrote straight to the final name; a naive port that cleaned
    up ``output`` on failure would delete a *good* file produced earlier in the
    same run whenever two sources share a stem (``Show.avi`` + ``Show.mkv``
    both target ``Show_fixed.mp4``, and the second one failing is routine -
    ``-map 0:a:0`` fails on any file with no audio track).
    """
    temp = output.with_name(f".{output.name}.{os.getpid()}.part")

    completed = run(
        [
            "ffmpeg",
            # -nostdin so ffmpeg cannot put an interactive terminal into raw
            # mode. DEVNULL as well, so the guarantee does not rely on the flag.
            "-nostdin",
            # -y: the target is our own temp file, so overwriting a leftover
            # from a killed run is correct. Without it ffmpeg silently refuses
            # and, on some versions, still exits 0 - a false success.
            "-y",
            "-i",
            str(source),
            *FFMPEG_ARGS,
            str(temp),
        ],
        check=False,
        stdin=subprocess.DEVNULL,
    )

    if completed.returncode != 0 or not temp.exists() or temp.stat().st_size == 0:
        temp.unlink(missing_ok=True)
        return False

    temp.replace(output)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="fix-codecs",
        description="🔧 Re-encode media to h265/aac mp4 so it Direct Plays.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    add_bool_flag(
        parser,
        "--delete-original",
        dest="delete_original",
        help="Delete each source file after a successful convert",
    )
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", True),
        help="Print what would be converted, change nothing",
    )

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    if not args.path:
        warning("Error: You must provide a path with --path=")
        return 1

    # Binary check before the path check, matching the shell version's order,
    # so a missing ffmpeg is reported even when the path is also wrong.
    require_binary("ffmpeg", hint="Install FFmpeg first.")

    root = scan_root(args.path)

    note(f"Scanning: {args.path}")
    note(f"Delete original after conversion: {str(args.delete_original).lower()}")
    note(f"Dry run: {str(args.dry_run).lower()}")
    note("----------------------------------------------------")

    converted = 0
    failed = 0

    for path in iter_files(root, extensions=SCAN_EXTENSIONS):
        # Don't re-encode our own output on a second run. Announced rather than
        # silent, because scene "PROPER/FIXED" repacks legitimately end in
        # _fixed and would otherwise vanish from the listing with no trace.
        if path.stem.endswith("_fixed"):
            info(f"⏭️  Skipping (already _fixed): {path}")
            continue

        output = path.with_name(f"{path.stem}_fixed.mp4")

        if args.dry_run:
            info(f"[DRY RUN] Would re-encode: {path} -> {output}")
            if args.delete_original:
                info(f"[DRY RUN] Would delete original: {path}")
            continue

        # Never silently replace an existing conversion; the user may have
        # produced it deliberately, and there is no way to tell it apart from
        # one this run just made for a different same-stem source.
        if output.exists():
            warning(f"⏭️  Skipping (output already exists): {output}")
            continue

        log(f"Processing: {path}")

        if not encode(path, output):
            warning(f"❌ ffmpeg failed for: {path}")
            failed += 1
            continue

        log(f"✅ Converted to: {output}")
        converted += 1

        if args.delete_original:
            try:
                path.unlink()
            except OSError as exc:
                warning(f"  ✗ Could not delete {path}: {exc}")
                continue
            warning(f"🗑 Deleted original: {path}")

    if args.dry_run:
        log("💡 Dry run complete. Nothing was actually changed.")
        return 0

    # Summary and the non-zero exit on failure are both new; the shell version
    # printed nothing and always exited 0 from the loop.
    success(f"✅ Converted: {converted}")
    if failed:
        warning(f"❌ Failed:    {failed}")
        return 1
    return 0


if __name__ == "__main__":
    run_cli(main)
