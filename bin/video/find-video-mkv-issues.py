#!/usr/bin/env python3
"""🎬 Scan MKV files and estimate Plex direct-play compatibility.

Usage:
  find-video-mkv-issues.py --path=/media/path [--recursive]

Options:
  --path=PATH     Required path to scan
  --recursive     Recursively scan subfolders (default: false)
  --help          Show help

Examples:
  find-video-mkv-issues.py --path=./Movies
  find-video-mkv-issues.py --path=/mnt/media --recursive

Requires ffprobe. The shell version also required `find` and `bc`; neither is
needed now.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    ffprobe_entries,
    format_bytes,
    info,
    iter_files,
    note,
    require_binary,
    run,
    run_cli,
    scan_root,
    success,
    warning,
)

__version__ = "2.1.0"

# (score penalty, note). An empty note means "penalise silently", matching the
# shell version, which docked a point for ac3/eac3 without explaining why.
VIDEO_PENALTIES: dict[str, tuple[int, str]] = {
    "h264": (0, ""),
    "hevc": (1, "HEVC may transcode on older clients"),
    "h265": (1, "HEVC may transcode on older clients"),
    "vp9": (3, "VP9 support inconsistent"),
    "av1": (5, "AV1 unsupported on many Plex devices"),
    "vc1": (7, "Legacy video codec"),
    "wmv3": (7, "Legacy video codec"),
    "mpeg2video": (5, "MPEG2 commonly transcoded"),
}
VIDEO_DEFAULT = (8, "Unknown or niche video codec")

AUDIO_PENALTIES: dict[str, tuple[int, str]] = {
    "aac": (0, ""),
    "ac3": (1, ""),
    "eac3": (1, ""),
    "dts": (3, "DTS unsupported on many TVs/mobile devices"),
    "truehd": (5, "TrueHD frequently transcoded"),
    "flac": (3, "FLAC audio may transcode"),
    "mp2": (5, "MP2 audio uncommon"),
}
AUDIO_DEFAULT = (4, "Unknown or niche audio codec")

SUBTITLE_PENALTIES: dict[str, tuple[int, str]] = {
    "pgs": (2, "PGS subtitles may force transcoding"),
    "hdmv_pgs_subtitle": (2, "PGS subtitles may force transcoding"),
    "dvd_subtitle": (2, "Image subtitles may transcode"),
}


def rate_video(
    video_codec: str,
    audio_codec: str,
    subtitle_codec: str,
    width: int,
    bitrate: int,
) -> tuple[int, str]:
    """Score a file 0-10 for Plex direct play, with the reasons for the deductions."""
    score = 10
    reasons: list[str] = []

    for table, default, codec in (
        (VIDEO_PENALTIES, VIDEO_DEFAULT, video_codec),
        (AUDIO_PENALTIES, AUDIO_DEFAULT, audio_codec),
        (SUBTITLE_PENALTIES, (0, ""), subtitle_codec),
    ):
        penalty, reason = table.get(codec, default)
        score -= penalty
        if reason:
            reasons.append(reason)

    if width >= 3840:
        score -= 1
        reasons.append("4K playback may struggle on weaker devices")

    mbps = bitrate // 1_000_000
    if mbps > 60:
        score -= 2
        reasons.append("Very high bitrate")
    elif mbps > 30:
        score -= 1
        reasons.append("High bitrate")

    score = max(0, min(10, score))
    # ";" with no space: the shell version's `IFS='; '; echo "${reasons[*]}"`
    # joins on the FIRST character of IFS only.
    return score, ";".join(reasons) if reasons else "Excellent Plex compatibility"


def as_int(value: str) -> int:
    """ffprobe prints 'N/A' for absent fields; treat anything non-numeric as 0."""
    return int(value) if value.isdigit() else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="find-video-mkv-issues",
        description="🎬 Scan MKV files and estimate Plex direct-play compatibility.",
        epilog=(
            "Examples:\n"
            "  find-video-mkv-issues.py --path=./Movies\n"
            "  find-video-mkv-issues.py --path=/mnt/media --recursive"
        ),
    )
    parser.add_argument("--path", default="", metavar="PATH", help="Required path to scan")
    add_bool_flag(parser, "--recursive", help="Recursively scan subfolders (default: false)")

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    require_binary("ffprobe", hint="Install FFmpeg: brew install ffmpeg")

    if not args.path:
        warning("--path is required")
        parser.print_help()
        return 1

    root = scan_root(args.path)

    note(f"Scanning: {args.path}")
    note(f"Recursive: {str(args.recursive).lower()}")
    note("----------------------------------------------------")

    total = excellent = good = poor = bad = 0

    # macOS ._ sidecars are skipped: they are never real media, and ffprobing
    # each one would waste a subprocess per file on a NAS scan. The shell
    # version probed them, failed, and counted each one as Bad - so Total and
    # Bad both read lower here on a library that has them.
    for path in iter_files(root, extensions=["mkv"], recursive=args.recursive):
        total += 1

        note("Checking:")
        print(f"  {path}", flush=True)

        readable = run(["ffprobe", "-v", "error", str(path)], check=False, capture=True)
        if readable.returncode != 0:
            warning("  Corrupt or unreadable file")
            print(flush=True)
            bad += 1
            continue

        video_codec = (
            ffprobe_entries(
                path, "stream=codec_name", stream="v:0", fmt="default=noprint_wrappers=1:nokey=1"
            )
            or "unknown"
        )
        audio_codec = (
            ffprobe_entries(
                path, "stream=codec_name", stream="a:0", fmt="default=noprint_wrappers=1:nokey=1"
            )
            or "unknown"
        )
        subtitle_codec = (
            ffprobe_entries(
                path, "stream=codec_name", stream="s:0", fmt="default=noprint_wrappers=1:nokey=1"
            )
            or "none"
        )
        width_raw = ffprobe_entries(
            path, "stream=width", stream="v:0", fmt="default=noprint_wrappers=1:nokey=1"
        )
        bitrate_raw = ffprobe_entries(
            path, "format=bit_rate", fmt="default=noprint_wrappers=1:nokey=1"
        )
        width = as_int(width_raw)
        bitrate = as_int(bitrate_raw)

        try:
            filesize = path.stat().st_size
        except OSError:
            filesize = 0

        score, notes = rate_video(video_codec, audio_codec, subtitle_codec, width, bitrate)

        print(f"  Size      : {format_bytes(filesize)}", flush=True)
        print(f"  Video     : {video_codec}", flush=True)
        print(f"  Audio     : {audio_codec}", flush=True)
        print(f"  Subtitles : {subtitle_codec}", flush=True)
        # `is not None` rather than truthiness: the shell version gated on the
        # value being numeric, so a literal 0 still printed its line.
        if width_raw.isdigit():
            print(f"  Resolution: {width}px", flush=True)
        if bitrate_raw.isdigit():
            print(f"  Bitrate   : {bitrate // 1_000_000} Mbps", flush=True)

        if score >= 9:
            success(f"  Plex Score: {score}/10")
            excellent += 1
        elif score >= 7:
            info(f"  Plex Score: {score}/10")
            good += 1
        elif score >= 4:
            note(f"  Plex Score: {score}/10")
            poor += 1
        else:
            warning(f"  Plex Score: {score}/10")
            bad += 1

        print(f"  Notes     : {notes}", flush=True)
        print(flush=True)

    note("----------------------------------------------------")
    success("Scan complete")
    print(flush=True)
    print(f"Total Files : {total}", flush=True)
    print(f"Excellent   : {excellent}", flush=True)
    print(f"Good        : {good}", flush=True)
    print(f"Poor        : {poor}", flush=True)
    print(f"Bad         : {bad}", flush=True)
    return 0


if __name__ == "__main__":
    run_cli(main)
