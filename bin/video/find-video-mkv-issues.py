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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media import probe_media
from report import FAIL, NOTE, SAME, WARN, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    format_bytes,
    info,
    iter_files,
    note_settings,
    require_binary,
    run_cli,
    scan_root,
)

__version__ = "3.0.0"

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


class Rating(Outcome):
    """Everything a scan can conclude about a file, in summary order."""

    # Excellent files need nothing doing, so they are counted silently.
    EXCELLENT = (SAME, "", "Excellent", Listing.COUNT)
    GOOD = (NOTE, "good", "Good")
    POOR = (WARN, "poor", "Poor")
    BAD = (FAIL, "bad", "Bad", Listing.ALL)
    # DELIBERATE DIVERGENCE: an unreadable file used to be counted as Bad. It
    # has its own row now, since "could not be probed" and "probed and scored
    # 0-3" call for different fixes.
    UNREADABLE = (FAIL, "unreadable", "Unreadable", Listing.ALL)


# Best first: a score lands in the first tier whose floor it reaches.
TIERS: tuple[tuple[int, Rating], ...] = (
    (9, Rating.EXCELLENT),
    (7, Rating.GOOD),
    (4, Rating.POOR),
    (0, Rating.BAD),
)


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


def tier(score: int) -> Rating:
    """The rating for a 0-10 score."""
    return next(rating for floor, rating in TIERS if score >= floor)


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

    # An empty --path reads "❌ --path is required" without the usage block
    # the shell version printed after it.
    root = scan_root(args.path)

    note_settings(("Scanning", args.path), ("Recursive", args.recursive))
    started = time.monotonic()

    # macOS ._ sidecars are skipped: they are never real media, and ffprobing
    # each one would waste a subprocess per file on a NAS scan. The shell
    # version probed them, failed, and counted each one as Bad - so the file
    # count and Bad both read lower here on a library that has them.
    files = list(iter_files(root, extensions=["mkv"], recursive=args.recursive))
    tally = Tally(Rating)
    with tally.progress(len(files)) as progress:
        for path in files:
            progress.step(str(path))
            rate_file(tally, path)

    tally.summary(
        "Summary",
        facts=[plural(len(files), "file"), duration(time.monotonic() - started)],
    )
    return 0


def rate_file(tally: Tally[Rating], path: Path) -> None:
    """Probe and score one file, recording it under its tier."""
    name = str(path)
    probe = probe_media(path)
    if probe is None:
        reason = "corrupt or unreadable file"
        tally.flag(Rating.UNREADABLE, name, reason)
        return

    video_codec = probe.codec("video") or "unknown"
    audio_codec = probe.codec("audio") or "unknown"
    subtitle_codec = probe.codec("subtitle") or "none"
    width = probe.width()
    bitrate = probe.bit_rate()

    try:
        filesize = path.stat().st_size
    except OSError:
        filesize = 0

    score, notes = rate_video(video_codec, audio_codec, subtitle_codec, width or 0, bitrate or 0)

    facts = [f"{score}/10", format_bytes(filesize), f"{video_codec}/{audio_codec}/{subtitle_codec}"]
    if width is not None:
        facts.append(f"{width}px")
    if bitrate is not None:
        facts.append(f"{bitrate // 1_000_000} Mbps")
    facts.append(notes)
    tally.record(tier(score), name, " · ".join(facts), item=f"{name}: {score}/10")


if __name__ == "__main__":
    run_cli(main)
