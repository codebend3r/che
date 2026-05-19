#!/usr/bin/env python3
"""
Detect videos with the "green and purple/magenta" decoding artifact.

This artifact appears when chroma planes (U/V) are corrupted, swapped,
or mishandled by the decoder. The result is an image dominated by
green and magenta hues with almost no other colors -- unwatchable.

Usage:
    python detect_green_magenta.py path/to/video.mp4
    python detect_green_magenta.py /path/to/folder --verbose
    python detect_green_magenta.py vids/ --samples 40 --threshold 0.7

Requires: opencv-python, numpy
    pip install opencv-python numpy
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v",
    ".flv", ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts",
}


def analyze_frame(frame):
    """
    Return (green_magenta_ratio, mean_saturation) for one BGR frame.

    green_magenta_ratio = fraction of saturated pixels whose hue falls
    in the green or magenta bands. In a healthy video this is usually
    well under 0.5; in a broken green/magenta video it sits near 1.0.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0]      # OpenCV hue range: 0-179 (half of 0-360 degrees)
    s = hsv[..., 1]      # saturation: 0-255

    # Only look at pixels with real color. Gray/near-gray pixels carry
    # no useful hue information and shouldn't sway the verdict.
    sat_mask = s > 40
    if sat_mask.sum() < 100:
        # Frame is essentially grayscale -- can't judge it.
        return None, float(s.mean())

    hues = h[sat_mask]

    # Green band: ~70-170 deg  -> OpenCV 35-85
    # Magenta band: ~260-340 deg -> OpenCV 130-170
    green_mask   = (hues >= 35)  & (hues <= 85)
    magenta_mask = (hues >= 130) & (hues <= 170)

    ratio = (green_mask.sum() + magenta_mask.sum()) / hues.size
    return float(ratio), float(s.mean())


def analyze_video(path, sample_count=20, threshold=0.65):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return {"path": str(path), "error": "could not open"}

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    if total > sample_count * 2:
        # Sample evenly, skipping the first/last 5% (intros, credits, black frames)
        start = int(total * 0.05)
        end   = int(total * 0.95)
        positions = np.linspace(start, end, sample_count, dtype=int)
    else:
        positions = None  # short or unknown-length file -- just read sequentially

    ratios, sats = [], []

    if positions is None:
        for _ in range(sample_count):
            ok, frame = cap.read()
            if not ok:
                break
            r, s = analyze_frame(frame)
            if r is not None:
                ratios.append(r)
            sats.append(s)
    else:
        for pos in positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
            ok, frame = cap.read()
            if not ok:
                continue
            r, s = analyze_frame(frame)
            if r is not None:
                ratios.append(r)
            sats.append(s)

    cap.release()

    if not ratios:
        return {"path": str(path), "error": "no usable (color) frames decoded"}

    avg_ratio = float(np.mean(ratios))
    avg_sat   = float(np.mean(sats))

    # Flag if the green/magenta dominance is high AND the frames are
    # actually saturated (otherwise we'd flag intentionally desaturated
    # cinematography that happens to lean cool/warm).
    flagged = avg_ratio >= threshold and avg_sat > 35

    return {
        "path": str(path),
        "frames_sampled": len(ratios),
        "green_magenta_ratio": round(avg_ratio, 3),
        "avg_saturation": round(avg_sat, 1),
        "flagged": flagged,
    }


def iter_videos(paths):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.suffix.lower() in VIDEO_EXTS:
                    yield f
        elif p.is_file():
            yield p
        else:
            print(f"[skip] {p}: not a file or directory", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description="Detect videos with the green/magenta chroma artifact."
    )
    ap.add_argument("paths", nargs="+",
                    help="Video files or directories to scan (directories are searched recursively)")
    ap.add_argument("--samples", type=int, default=20,
                    help="Frames to sample per video (default: 20)")
    ap.add_argument("--threshold", type=float, default=0.65,
                    help="Fraction of saturated pixels that must be green or magenta to flag (default: 0.65)")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Print every video, not just flagged ones")
    args = ap.parse_args()

    bad = []
    any_seen = False
    for v in iter_videos(args.paths):
        any_seen = True
        res = analyze_video(v, sample_count=args.samples, threshold=args.threshold)
        if "error" in res:
            print(f"[skip] {v}: {res['error']}", file=sys.stderr)
            continue
        tag = "BAD " if res["flagged"] else "ok  "
        line = f"{tag} ratio={res['green_magenta_ratio']:.2f} sat={res['avg_saturation']:>5.1f}  {v}"
        if res["flagged"] or args.verbose:
            print(line)
        if res["flagged"]:
            bad.append(str(v))

    if not any_seen:
        print("No video files found.", file=sys.stderr)
        sys.exit(2)

    if bad:
        print(f"\n{len(bad)} video(s) flagged as green/magenta-tinted:", file=sys.stderr)
        for b in bad:
            print(f"  {b}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
