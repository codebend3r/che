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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media import LIBRARY_EXTENSIONS
from report import FAIL, OK, WARN, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    info,
    iter_files,
    log,
    require_binary,
    run,
    run_cli,
    scan_root,
    warning,
)

__version__ = "4.0.0"


class Playback(Outcome):
    """Everything a playback check can conclude about a file, in summary order."""

    PLAYED = (OK, "", "Played cleanly", Listing.COUNT)
    COMPLAINED = (WARN, "complained", "Played, mpv complained")
    TIMED_OUT = (FAIL, "timed out", "Timed out", Listing.ALL)
    UNPLAYABLE = (FAIL, "unplayable", "Unplayable", Listing.ALL)


MPV = [
    "mpv",
    # --no-config so a stale ~/.config/mpv/mpv.conf cannot emit warnings that
    # would be misread as playback failures.
    "--no-config",
    "--no-audio",
    "--vo=null",
    "--really-quiet",
    "--frames=1",
]


def check(tally: Tally[Playback], root: Path, path: Path, *, verbose: bool) -> None:
    """Decode one frame of ``path`` and record how it went."""
    name = str(path.relative_to(root))
    try:
        completed = run([*MPV, str(path)], check=False, capture=True, timeout=30)
    except subprocess.TimeoutExpired:
        # The shell version had no timeout, so an mpv wedged on a stalled
        # SMB read blocked the scan forever.
        tally.record(Playback.TIMED_OUT, name, "no frame within 30s")
        return

    # DELIBERATE DIVERGENCE: the shell version ran mpv as a simple command
    # under `set -e`, so the FIRST unplayable file killed the whole scan
    # before it could even print which file it was. This records the
    # failure and carries on. The verdict is the exit code alone; stderr
    # noise is reported but is not by itself a failure, since --really-quiet
    # does not suppress every warning mpv can emit.
    stderr = (completed.stderr or "").strip()
    last = stderr.splitlines()[-1].strip() if stderr else ""
    if completed.returncode != 0:
        reason = last or f"mpv exited {completed.returncode}"
        tally.record(Playback.UNPLAYABLE, name, reason, item=f"{name}: {reason}")
    elif stderr:
        tally.record(Playback.COMPLAINED, name, last)
    else:
        tally.record(Playback.PLAYED, name)
        # The shell version gated its per-file line on `[[ -z "$VERBOSE" ]]`,
        # but VERBOSE is the literal string "false" when unset, which is never
        # empty, so the line never printed and --verbose did nothing. Here it
        # also names every clean file, which is otherwise only counted.
        if verbose:
            tally.report.event(Playback.PLAYED.tone, "played", name)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="validate-video-files",
        description="🩺 Check .mp4/.mkv files are playable by decoding one frame with mpv.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    add_bool_flag(parser, "--verbose", help="Print each file as it is checked")
    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)
    started = time.monotonic()

    # An empty --path reads "--path is required", where the shell version
    # reported `'' is not a valid directory`.
    root = scan_root(args.path)

    require_binary("mpv", hint="Install it using Homebrew:\n  brew install mpv")

    # Collected up front so the progress line can show a total: each file
    # costs an mpv launch, so the walk itself is negligible.
    files = list(iter_files(root, extensions=LIBRARY_EXTENSIONS))
    tally = Tally(Playback)
    with tally.progress(len(files)) as progress:
        for path in files:
            progress.step(str(path.relative_to(root)))
            check(tally, root, path, verbose=args.verbose)

    tally.summary(
        "Summary",
        facts=[plural(len(files), "file"), duration(time.monotonic() - started)],
        notes=[f"Scanned {root}"],
    )
    print()
    if bad := tally.count(Playback.TIMED_OUT, Playback.UNPLAYABLE):
        warning(f"❌ {bad} of {plural(len(files), 'file')} failed playback.")
        return 1
    log(f"🎉 All {plural(len(files), 'file')} played back.")
    return 0


if __name__ == "__main__":
    run_cli(main)
