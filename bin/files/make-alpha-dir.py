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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import build_parser, info, run_cli, warning

BUCKETS = ("#", *string.ascii_uppercase)


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
    failures = 0
    for bucket in BUCKETS:
        try:
            (root / bucket).mkdir(exist_ok=True)
        except OSError as exc:
            warning(f"mkdir: {bucket}: {exc.strerror or exc}")
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    run_cli(main)
