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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media import CODEC_SCAN_EXTENSIONS
from report import FAIL, NOTE, OK, PLAN, WARN, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    dry_run_complete,
    env_bool,
    info,
    iter_files,
    log,
    note_settings,
    require_binary,
    run,
    run_cli,
    scan_root,
    warning,
)

__version__ = "4.0.0"


class Encode(Outcome):
    """Everything a re-encode run can conclude about a file, in summary order."""

    CONVERTED = (OK, "converted", "Converted")
    WOULD_CONVERT = (PLAN, "would encode", "Would convert")
    ALREADY_FIXED = (NOTE, "skipped", "Already _fixed")
    OUTPUT_EXISTS = (WARN, "skipped", "Output exists")
    KEPT_ORIGINAL = (WARN, "kept", "Original not deleted")
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


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

    # Binary check before the directory check, matching the shell version's
    # order, so a missing ffmpeg is reported even when the path is also wrong.
    # An empty --path reads "--path is required" after it, where the shell
    # version said "Error: You must provide a path with --path=" before it.
    require_binary("ffmpeg", hint="Install FFmpeg first.")

    root = scan_root(args.path)

    note_settings(
        ("Scanning", args.path),
        ("Delete original after conversion", args.delete_original),
        ("Dry run", args.dry_run),
    )

    started = time.monotonic()
    tally = Tally(Encode)
    scanned = 0

    # No progress line: ffmpeg streams its own progress to the terminal, and
    # the walk streams too, so there is no total to count against.
    for path in iter_files(root, extensions=CODEC_SCAN_EXTENSIONS):
        scanned += 1
        shown = str(path.relative_to(root))
        # Don't re-encode our own output on a second run. Announced rather than
        # silent, because scene "PROPER/FIXED" repacks legitimately end in
        # _fixed and would otherwise vanish from the listing with no trace.
        if path.stem.endswith("_fixed"):
            tally.record(Encode.ALREADY_FIXED, shown, "already _fixed")
            continue

        output = path.with_name(f"{path.stem}_fixed.mp4")

        # Never silently replace an existing conversion; the user may have
        # produced it deliberately, and there is no way to tell it apart from
        # one this run just made for a different same-stem source. Checked
        # before the dry-run branch so a preview reports the same skips.
        if output.exists():
            reason = f"{output.name} already exists"
            tally.flag(Encode.OUTPUT_EXISTS, shown, reason)
            continue

        if args.dry_run:
            then = "; would delete the original" if args.delete_original else ""
            tally.record(Encode.WOULD_CONVERT, shown, f"to {output.name}{then}")
            continue

        info(f"🔧 Encoding {shown}")
        if not encode(path, output):
            tally.flag(Encode.FAILED, shown, "ffmpeg failed")
            continue

        tally.record(Encode.CONVERTED, shown, f"to {output.name}")
        if args.delete_original:
            try:
                path.unlink()
            except OSError as exc:
                tally.flag(Encode.KEPT_ORIGINAL, shown, str(exc))

    notes = ["Existing conversions are never overwritten."]
    if args.delete_original and not args.dry_run:
        notes.append("Each original was deleted only after its conversion succeeded.")
    tally.summary(
        "Preview" if args.dry_run else "Summary",
        facts=[plural(scanned, "file"), duration(time.monotonic() - started)],
        notes=notes,
    )
    print()
    if args.dry_run:
        dry_run_complete()
        return 0

    # The non-zero exit on failure is new; the shell version printed nothing
    # and always exited 0 from the loop.
    if count := tally.count(Encode.FAILED):
        warning(f"❌ {plural(count, 'file')} failed to convert.")
        return 1
    log("🎉 Conversion complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
