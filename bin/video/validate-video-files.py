#!/usr/bin/env python3
"""🩺 Check .mp4/.mkv files are playable by decoding a single frame with mpv.

Usage:
  validate-video-files.py --path=/path/to/media [--verbose]

Options:
  --path=DIR    Directory to scan (required)
  --verbose     Print each file as it is checked
  --help        Show help
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media import LIBRARY_EXTENSIONS
from utils import (
    add_bool_flag,
    build_parser,
    info,
    iter_files,
    require_binary,
    run,
    run_cli,
    scan_root,
    success,
    warning,
)

__version__ = "3.1.0"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="validate-video-files",
        description="🩺 Check .mp4/.mkv files are playable by decoding one frame with mpv.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    add_bool_flag(parser, "--verbose", help="Print each file as it is checked")
    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    # An empty --path reads "--path is required", where the shell version
    # reported `'' is not a valid directory`.
    root = scan_root(args.path)

    require_binary("mpv", hint="Install it using Homebrew:\n  brew install mpv")

    checked = 0
    bad: list[Path] = []

    for path in iter_files(root, extensions=LIBRARY_EXTENSIONS):
        # The shell version gated this on `[[ -z "$VERBOSE" ]]`, but VERBOSE is
        # the literal string "false" when unset, which is never empty - so the
        # line never printed and --verbose did nothing. Wired up properly here.
        if args.verbose:
            info(f"Checking: {path}")

        checked += 1
        try:
            completed = run(
                [
                    "mpv",
                    # --no-config so a stale ~/.config/mpv/mpv.conf cannot emit
                    # warnings that would be misread as playback failures.
                    "--no-config",
                    "--no-audio",
                    "--vo=null",
                    "--really-quiet",
                    "--frames=1",
                    str(path),
                ],
                check=False,
                capture=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            # The shell version had no timeout, so an mpv wedged on a stalled
            # SMB read blocked the scan forever.
            warning(f"❌ Timed out reading: {path}")
            bad.append(path)
            continue

        # DELIBERATE DIVERGENCE: the shell version ran mpv as a simple command
        # under `set -e`, so the FIRST unplayable file killed the whole scan
        # before it could even print which file it was. This records the
        # failure and carries on. The verdict is the exit code alone; stderr
        # noise is reported but is not by itself a failure, since --really-quiet
        # does not suppress every warning mpv can emit.
        if completed.returncode != 0:
            warning(f"❌ Unplayable or error in: {path}")
            bad.append(path)
        elif (completed.stderr or "").strip():
            warning(f"⚠️  Played, but mpv complained about: {path}")

    print()
    if bad:
        warning(f"❌ {len(bad)} of {checked} file(s) failed playback.")
        return 1

    success(f"✅ All {checked} file(s) played back cleanly.")
    return 0


if __name__ == "__main__":
    run_cli(main)
