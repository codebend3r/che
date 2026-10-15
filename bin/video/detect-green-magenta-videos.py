#!/usr/bin/env python3
"""
Detect videos with the "green and purple/magenta" decoding artifact.

This artifact appears when chroma planes (U/V) are corrupted, swapped,
or mishandled by the decoder. The result is an image dominated by
green and magenta hues with almost no other colors -- unwatchable.

Usage:
    detect-green-magenta-videos.py path/to/video.mp4
    detect-green-magenta-videos.py /path/to/folder --verbose
    detect-green-magenta-videos.py vids/ --samples=40 --threshold=0.7

Requires: opencv-python, numpy
    pip install opencv-python numpy

This is the only script in the repo that needs third-party packages. Rather
than a separate bash launcher, it re-execs itself under a dedicated venv when
cv2 is missing from the interpreter it was started with - Homebrew Python is
PEP 668 "externally managed" and refuses plain pip installs, so the packages
have to live somewhere isolated. Override the location with $DETECT_GM_PYTHON.
"""

import os
import sys
from pathlib import Path
from typing import NamedTuple, NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Standard library only, so this imports the same under the venv interpreter.
from utils import add_bool_flag, build_parser, iter_files, parse_count, run_cli

__version__ = "2.0.0"

VENV_PYTHON = Path(
    os.environ.get("DETECT_GM_PYTHON", Path.home() / ".venvs" / "green-magenta" / "bin" / "python")
)


def _reexec_under_venv() -> NoReturn:
    """Hand off to the venv interpreter when cv2 is not importable here.

    ``_DETECT_GM_REEXEC`` guards against a loop if the venv itself is missing
    the packages: the second run reaches the error path instead of re-execing
    forever.
    """
    if os.environ.get("_DETECT_GM_REEXEC"):
        print(
            f"❌ {VENV_PYTHON} is missing cv2 or numpy. Run:\n"
            f"  {VENV_PYTHON} -m pip install opencv-python numpy",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not os.access(VENV_PYTHON, os.X_OK):
        print(
            f"❌ Python venv not found: {VENV_PYTHON}\n"
            "Bootstrap with:\n"
            "  python3 -m venv $HOME/.venvs/green-magenta\n"
            "  $HOME/.venvs/green-magenta/bin/pip install opencv-python numpy",
            file=sys.stderr,
        )
        raise SystemExit(1)

    os.environ["_DETECT_GM_REEXEC"] = "1"
    os.execv(  # noqa: S606 - absolute interpreter path, no shell involved
        str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]]
    )


# --help and bare usage must work on a machine with no venv at all, so the
# import is skipped entirely for those. The bash launcher checked --help before
# it checked for the venv, and asking someone to bootstrap OpenCV just to read
# the usage text is a poor answer to "how do I use this?".
_WANTS_HELP = len(sys.argv) == 1 or any(a in ("-h", "--help") for a in sys.argv[1:])

if not _WANTS_HELP:
    try:
        # ImportError, not ModuleNotFoundError: a half-installed or
        # ABI-mismatched OpenCV - the common opencv-on-macOS failure - raises
        # plain ImportError, which would otherwise escape as a raw traceback.
        import cv2
        import numpy as np
    except ImportError:
        _reexec_under_venv()

VIDEO_EXTS = (
    "mp4",
    "mkv",
    "avi",
    "mov",
    "webm",
    "m4v",
    "flv",
    "wmv",
    "mpg",
    "mpeg",
    "ts",
    "m2ts",
)


class SkipVideo(Exception):
    """A video that cannot be judged; the message says why."""


class Verdict(NamedTuple):
    ratio: float  # mean green/magenta fraction, to 3 places
    saturation: float  # mean saturation, to 1 place
    flagged: bool


def analyze_frame(frame):
    """
    Return (green_magenta_ratio, mean_saturation) for one BGR frame.

    green_magenta_ratio = fraction of saturated pixels whose hue falls
    in the green or magenta bands. In a healthy video this is usually
    well under 0.5; in a broken green/magenta video it sits near 1.0.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0]  # OpenCV hue range: 0-179 (half of 0-360 degrees)
    s = hsv[..., 1]  # saturation: 0-255

    # Only look at pixels with real color. Gray/near-gray pixels carry
    # no useful hue information and shouldn't sway the verdict.
    sat_mask = s > 40
    if sat_mask.sum() < 100:
        # Frame is essentially grayscale -- can't judge it.
        return None, float(s.mean())

    hues = h[sat_mask]

    # Green band: ~70-170 deg  -> OpenCV 35-85
    # Magenta band: ~260-340 deg -> OpenCV 130-170
    green_mask = (hues >= 35) & (hues <= 85)
    magenta_mask = (hues >= 130) & (hues <= 170)

    ratio = (green_mask.sum() + magenta_mask.sum()) / hues.size
    return float(ratio), float(s.mean())


def sample_frames(cap, sample_count):
    """Yield up to ``sample_count`` decoded frames from an open capture."""
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if total <= sample_count * 2:
        # Short or unknown-length file -- just read sequentially.
        for _ in range(sample_count):
            ok, frame = cap.read()
            if not ok:
                return
            yield frame
        return

    # Sample evenly, skipping the first/last 5% (intros, credits, black frames)
    start = int(total * 0.05)
    end = int(total * 0.95)
    for pos in np.linspace(start, end, sample_count, dtype=int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
        ok, frame = cap.read()
        if ok:
            yield frame


def analyze_video(path, sample_count=20, threshold=0.65) -> Verdict:
    """Judge one video, or raise ``SkipVideo`` when it cannot be judged."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SkipVideo("could not open")

    ratios, sats = [], []
    for frame in sample_frames(cap, sample_count):
        r, s = analyze_frame(frame)
        if r is not None:
            ratios.append(r)
        sats.append(s)
    cap.release()

    if not ratios:
        raise SkipVideo("no usable (color) frames decoded")

    avg_ratio = float(np.mean(ratios))
    avg_sat = float(np.mean(sats))

    # Flag if the green/magenta dominance is high AND the frames are
    # actually saturated (otherwise we'd flag intentionally desaturated
    # cinematography that happens to lean cool/warm).
    flagged = avg_ratio >= threshold and avg_sat > 35

    return Verdict(round(avg_ratio, 3), round(avg_sat, 1), flagged)


def iter_videos(paths):
    """Yield every video under the given files and directories.

    Directories go through the repo's ``iter_files``, where this script used
    to walk them itself. DELIBERATE DIVERGENCE from that walk: a file named
    just ``.mkv`` now matches, FIFOs and sockets with a video extension are
    no longer yielded (opening a FIFO blocks forever), and a folder that
    cannot be read is reported on stderr rather than silently passed over.
    """
    for p in map(Path, paths):
        if p.is_dir():
            yield from iter_files(p, extensions=VIDEO_EXTS)
        elif p.is_file():
            yield p
        else:
            print(f"[skip] {p}: not a file or directory", file=sys.stderr)


def main(argv=None):
    # build_parser like every other script, so a usage error exits 1 with the
    # full help, where plain argparse exited 2. `-v` is gone with it: the repo
    # takes long flags only, and neither the menu nor the completions offered it.
    parser = build_parser(
        prog="detect-green-magenta-videos",
        description="Detect videos with the green/magenta chroma artifact.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Video files or directories to scan (directories are searched recursively)",
    )
    # A string checked by parse_count: `type=int` let 0 through, which skipped
    # every video, and a negative count, which crashed numpy on the first one.
    parser.add_argument(
        "--samples", default="20", metavar="N", help="Frames to sample per video (default: 20)"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.65,
        metavar="RATIO",
        help="Fraction of saturated pixels that must be green or magenta to flag (default: 0.65)",
    )
    add_bool_flag(parser, "--verbose", help="Print every video, not just flagged ones")
    args = parser.parse_args(argv)
    samples = parse_count(args.samples, "--samples", minimum=1)

    # The bash launcher printed these before exec'ing, and the rest of the repo
    # opens the same way. After parse_args, so --help stays clean.
    print(f"Running command in {Path.cwd()}")
    print(f"Scanning: {' '.join(args.paths)}")
    print("----------------------------------------------------")

    bad = []
    any_seen = False
    for v in iter_videos(args.paths):
        any_seen = True
        try:
            verdict = analyze_video(v, sample_count=samples, threshold=args.threshold)
        except SkipVideo as exc:
            print(f"[skip] {v}: {exc}", file=sys.stderr)
            continue
        if verdict.flagged or args.verbose:
            tag = "BAD " if verdict.flagged else "ok  "
            print(f"{tag} ratio={verdict.ratio:.2f} sat={verdict.saturation:>5.1f}  {v}")
        if verdict.flagged:
            bad.append(str(v))

    if not any_seen:
        print("No video files found.", file=sys.stderr)
        return 2

    if bad:
        print(f"\n{len(bad)} video(s) flagged as green/magenta-tinted:", file=sys.stderr)
        for b in bad:
            print(f"  {b}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # run_cli, like every other script: Ctrl-C now exits 130 quietly where it
    # used to dump a traceback.
    run_cli(main)
