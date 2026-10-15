#!/usr/bin/env python3
"""🎥 Report media files whose codecs or container fall outside the Direct Play set.

Usage:
  show-codecs.py --path=/path/to/media [--verbose]

Options:
  --path=DIR    Directory to scan (required)
  --verbose     Also print files that pass
  --help        Show help
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media import CODEC_SCAN_EXTENSIONS, probe_media
from utils import (
    add_bool_flag,
    build_parser,
    info,
    iter_files,
    log,
    note_settings,
    require_binary,
    run_cli,
    scan_root,
    warning,
)

__version__ = "3.1.0"

# The common safe set for Direct Play. Tuples, not sets, so the banner prints
# them in the order the shell version's arrays declared them.
ALLOWED_VIDEO_CODECS = ("h264", "hevc")
ALLOWED_AUDIO_CODECS = ("aac", "ac3", "eac3")
ALLOWED_CONTAINERS = ("mov", "mp4", "mkv")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="show-codecs",
        description="🎥 Report media files outside the Direct Play codec/container set.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    add_bool_flag(parser, "--verbose", help="Also print files that pass")
    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    note_settings(("Scanning", args.path), ("Verbose", args.verbose))

    root = scan_root(args.path)

    require_binary("ffprobe", hint="Install FFmpeg: brew install ffmpeg")

    print(f"Scanning for problematic codecs in: {args.path}")
    print(f"Allowed Video: {' '.join(ALLOWED_VIDEO_CODECS)}")
    print(f"Allowed Audio: {' '.join(ALLOWED_AUDIO_CODECS)}")
    print(f"Allowed Containers: {' '.join(ALLOWED_CONTAINERS)}")
    print("----------------------------------------------------")

    problems = 0

    for path in iter_files(root, extensions=CODEC_SCAN_EXTENSIONS):
        container = path.name.lower().rsplit(".", 1)[-1]

        # "unknown" when ffprobe itself FAILS (a corrupt file), matching the
        # shell version's `|| echo "unknown"`, or when it cannot name a codec.
        # A file that probes fine but has no audio track keeps the empty
        # string the shell version stored, so the cases stay distinguishable.
        #
        # DELIBERATE DIVERGENCE: the shell version's csv output read `ac3,`
        # for AC3 or E-AC3 audio in an MP4 on ffprobe 9 (see MediaProbe), so
        # every such file failed the allowed-codec check. They now pass.
        probe = probe_media(path)
        if probe is None:
            video_codec = audio_codec = "unknown"
        else:
            video_codec = probe.codec("video").lower()
            audio_codec = probe.codec("audio").lower()

        ok = (
            video_codec in ALLOWED_VIDEO_CODECS
            and audio_codec in ALLOWED_AUDIO_CODECS
            and container in ALLOWED_CONTAINERS
        )

        if not ok:
            problems += 1
            warning(f"❌ {path}")
            warning(f"Container: {container} | Video: {video_codec} | Audio: {audio_codec}")
        elif args.verbose:
            log(f"✅ {path}")
            log(f"Container: {container} | Video: {video_codec} | Audio: {audio_codec}")

    # DELIBERATE DIVERGENCE: the shell version always exited 0. Exiting 1 when
    # problems are found lets this gate a pipeline. Note a real library nearly
    # always has some non-Direct-Play file, so `show-codecs && next` will
    # usually stop - use `; ` rather than `&&` if that is not what you want.
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    run_cli(main)
