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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media import CODEC_SCAN_EXTENSIONS, probe_media
from report import FAIL, OK, SAME, WARN, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    info,
    iter_files,
    note_settings,
    require_binary,
    run_cli,
    scan_root,
)

__version__ = "4.0.0"

# The common safe set for Direct Play. Tuples, not sets, so the banner prints
# them in the order the shell version's arrays declared them.
ALLOWED_VIDEO_CODECS = ("h264", "hevc")
ALLOWED_AUDIO_CODECS = ("aac", "ac3", "eac3")
ALLOWED_CONTAINERS = ("mov", "mp4", "mkv")


class Check(Outcome):
    """Everything a scan can conclude about a file, in summary order."""

    OUTSIDE = (WARN, "outside set", "Outside Direct Play")
    # Printed only with --verbose (see main), counted either way.
    PASSES = (SAME, "", "Direct Play", Listing.COUNT)
    UNREADABLE = (FAIL, "unreadable", "Unreadable", Listing.ALL)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="show-codecs",
        description="🎥 Report media files outside the Direct Play codec/container set.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    add_bool_flag(parser, "--verbose", help="Also print files that pass")
    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    note_settings(
        ("Scanning", args.path),
        ("Verbose", args.verbose),
        ("Allowed video", " ".join(ALLOWED_VIDEO_CODECS)),
        ("Allowed audio", " ".join(ALLOWED_AUDIO_CODECS)),
        ("Allowed containers", " ".join(ALLOWED_CONTAINERS)),
    )

    root = scan_root(args.path)

    require_binary("ffprobe", hint="Install FFmpeg: brew install ffmpeg")

    started = time.monotonic()
    files = list(iter_files(root, extensions=CODEC_SCAN_EXTENSIONS))
    tally = Tally(Check)
    with tally.progress(len(files)) as progress:
        for path in files:
            progress.step(str(path))
            check_file(tally, path, verbose=args.verbose)

    tally.summary(
        "Summary",
        facts=[plural(len(files), "file"), duration(time.monotonic() - started)],
    )

    # DELIBERATE DIVERGENCE: the shell version always exited 0. Exiting 1 when
    # problems are found lets this gate a pipeline. Note a real library nearly
    # always has some non-Direct-Play file, so `show-codecs && next` will
    # usually stop - use `; ` rather than `&&` if that is not what you want.
    return 0 if tally.count(Check.OUTSIDE, Check.UNREADABLE) == 0 else 1


def check_file(tally: Tally[Check], path: Path, *, verbose: bool) -> None:
    """Probe one file and record whether it sits inside the Direct Play set."""
    name = str(path)
    container = path.name.lower().rsplit(".", 1)[-1]

    # "unknown" when ffprobe cannot name a codec. A file that probes fine but
    # has no audio track keeps the empty string the shell version stored, so
    # the cases stay distinguishable.
    #
    # DELIBERATE DIVERGENCE: the shell version's csv output read `ac3,`
    # for AC3 or E-AC3 audio in an MP4 on ffprobe 9 (see MediaProbe), so
    # every such file failed the allowed-codec check. They now pass.
    probe = probe_media(path)
    if probe is None:
        # The shell version's `|| echo "unknown"`: a corrupt file still counts
        # as a problem (and still fails the exit code), on its own row.
        reason = "ffprobe failed"
        tally.record(Check.UNREADABLE, name, reason, item=f"{name}: {reason}")
        return
    video_codec = probe.codec("video").lower()
    audio_codec = probe.codec("audio").lower()

    detail = (
        f"container {container} · video {video_codec or 'none'} · audio {audio_codec or 'none'}"
    )
    ok = (
        video_codec in ALLOWED_VIDEO_CODECS
        and audio_codec in ALLOWED_AUDIO_CODECS
        and container in ALLOWED_CONTAINERS
    )
    if not ok:
        tally.record(Check.OUTSIDE, name, detail, item=f"{name}: {detail}")
        return
    tally.record(Check.PASSES, name)
    if verbose:
        tally.report.event(OK, "passes", name, detail)


if __name__ == "__main__":
    run_cli(main)
