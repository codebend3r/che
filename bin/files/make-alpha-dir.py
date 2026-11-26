#!/usr/bin/env python3
"""🔤 Create the alphabetical bucket folders: ``#`` and ``A`` through ``Z``.

Usage:
  make-alpha-dir.py [--path=/path/to/parent]   (defaults to .)

Options:
  --path=DIR   Parent directory to create the buckets in (default: .)
  --help       Show help
"""

from __future__ import annotations

import string
import sys
import time
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from report import ADDED, FAIL, SAME, Listing, Outcome, Tally, duration, plural
from utils import build_parser, info, log, run_cli, warning

__version__ = "2.0.0"

BUCKETS = ("#", *string.ascii_uppercase)


class Bucket(Outcome):
    """Everything creating a bucket folder can conclude, in summary order."""

    CREATED = (ADDED, "created", "Created")
    EXISTED = (SAME, "", "Already there", Listing.COUNT)
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="make-alpha-dir",
        description="🔤 Create '#' and A-Z bucket folders under a parent directory.",
    )
    parser.add_argument(
        "--path",
        default=".",
        metavar="DIR",
        help="Parent directory to create the buckets in (default: .)",
    )

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)
    started = time.monotonic()

    root = Path(args.path or ".")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        warning(f"❌ Could not create {root}: {exc}")
        return 1

    # One `mkdir -p -- '#' {A..Z}` reported each failure and still created
    # every other operand, so a parent already holding a FILE named "A" ended
    # up with the remaining 26 buckets. Bailing on the first error would leave
    # a half-built bucket set behind.
    tally = Tally(Bucket)
    for bucket in BUCKETS:
        path = root / bucket
        if path.is_dir():
            tally.record(Bucket.EXISTED, bucket)
            continue
        tally.attempt(
            partial(path.mkdir, exist_ok=True), bucket, done=Bucket.CREATED, failed=Bucket.FAILED
        )

    tally.summary(
        "Summary",
        facts=[plural(len(BUCKETS), "bucket"), duration(time.monotonic() - started)],
        notes=[f"In {root.resolve()}"],
    )
    print()
    if count := tally.count(Bucket.FAILED):
        warning(f"⚠️  {plural(count, 'bucket')} could not be created. Every other bucket was.")
        return 1
    log("🎉 Buckets ready.")
    return 0


if __name__ == "__main__":
    run_cli(main)
