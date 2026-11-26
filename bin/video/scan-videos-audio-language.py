#!/usr/bin/env python3
"""🔊 Print the audio language tags of every video under a path.

Usage:
  scan-videos-audio-language.py --path=/path/to/media

Options:
  --path=DIR    Directory to scan (required)
  --help        Show help
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media import probe_media
from report import FAIL, NOTE, WARN, Listing, Outcome, Tally, duration, plural
from utils import (
    build_parser,
    info,
    iter_files,
    paint,
    require_binary,
    run_cli,
    scan_root,
)

__version__ = "4.0.0"

VIDEO_EXTENSIONS = ("mp4", "mkv", "avi", "mov", "flv", "wmv", "webm")

LANG_COLOR = {
    "eng": "\033[32m",  # Green
    "jpn": "\033[31m",  # Red
    "spa": "\033[33m",  # Yellow
    "fre": "\033[34m",  # Blue
    "ger": "\033[35m",  # Magenta
    "ita": "\033[36m",  # Cyan
    "kor": "\033[95m",  # Light Magenta
    "chi": "\033[91m",  # Light Red
    "por": "\033[92m",  # Light Green
    "rus": "\033[94m",  # Light Blue
}

DEFAULT_COLOR = "\033[90m"  # Gray for unknown languages


class Audio(Outcome):
    """Everything a scan can conclude about a file, in summary order."""

    # Every file prints: its languages are the data this script exists for.
    TAGGED = (NOTE, "audio", "Tagged", Listing.COUNT)
    UNTAGGED = (WARN, "untagged", "Not tagged")
    UNREADABLE = (FAIL, "unreadable", "Unreadable", Listing.ALL)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="scan-videos-audio-language",
        description="🔊 Print the audio language tags of every video under a path.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    # An empty --path reads "--path is required", where the shell version
    # reported `'' is not a valid directory`.
    root = scan_root(args.path)

    require_binary("ffprobe", hint="ffprobe (from ffmpeg) is required but not installed.")

    started = time.monotonic()
    files = list(iter_files(root, extensions=VIDEO_EXTENSIONS))
    tally = Tally(Audio)
    with tally.progress(len(files)) as progress:
        for path in files:
            progress.step(str(path))
            scan_file(tally, path)

    tally.summary(
        "Summary",
        facts=[plural(len(files), "file"), duration(time.monotonic() - started)],
    )
    return 0


def scan_file(tally: Tally[Audio], path: Path) -> None:
    """Record one file's audio language tags."""
    name = str(path)

    # Telling "no language tags" apart from "could not be read" matters:
    # the shell version aborted the whole scan on an unreadable file
    # (`set -e` on a failing command substitution), so it never had to
    # render the difference.
    probe = probe_media(path)
    if probe is None:
        reason = "ffprobe failed"
        tally.flag(Audio.UNREADABLE, name, reason)
        return

    # DELIBERATE DIVERGENCE: the shell version's csv output read `und,`
    # for AC3 or E-AC3 audio in an MP4 on ffprobe 9 (see MediaProbe), and
    # a bare `,` when such a stream had no tag. Both now read cleanly.
    languages = probe.languages("audio")
    if not languages:
        tally.record(Audio.UNTAGGED, name, "unknown or not tagged")
        return

    # Each language keeps its own colour inside the otherwise dim detail.
    colored = " ".join(paint(lang, LANG_COLOR.get(lang, DEFAULT_COLOR)) for lang in languages)
    tally.record(Audio.TAGGED, name, colored)


if __name__ == "__main__":
    run_cli(main)
