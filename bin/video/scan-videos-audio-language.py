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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media import probe_media
from utils import (
    build_parser,
    info,
    iter_files,
    paint,
    require_binary,
    run_cli,
    scan_root,
    warning,
)

__version__ = "3.1.0"

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

    for path in iter_files(root, extensions=VIDEO_EXTENSIONS):
        info(f"File: {path}")

        # Telling "no language tags" apart from "could not be read" matters:
        # the shell version aborted the whole scan on an unreadable file
        # (`set -e` on a failing command substitution), so it never had to
        # render the difference.
        probe = probe_media(path)
        if probe is None:
            warning(f"Audio language(s): {paint('Unreadable - ffprobe failed', DEFAULT_COLOR)}")
            continue

        # DELIBERATE DIVERGENCE: the shell version's csv output read `und,`
        # for AC3 or E-AC3 audio in an MP4 on ffprobe 9 (see MediaProbe), and
        # a bare `,` when such a stream had no tag. Both now read cleanly.
        languages = probe.languages("audio")
        if not languages:
            info(f"Audio language(s): {paint('Unknown or not tagged', DEFAULT_COLOR)}")
            continue

        colored = " ".join(paint(lang, LANG_COLOR.get(lang, DEFAULT_COLOR)) for lang in languages)
        info(f"Audio language(s): {colored} ")

    return 0


if __name__ == "__main__":
    run_cli(main)
