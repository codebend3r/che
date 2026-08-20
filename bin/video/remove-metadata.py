#!/usr/bin/env python3
"""🧼 Strip all metadata from video files recursively, using exiftool.

Runs: exiftool -all= -overwrite_original -r -progress -i '*/._*' -ext <ext>...

Usage:
  remove-metadata.py --path=/path/to/files [--exts=comma,separated,exts]

Options:
  --path=DIR    Directory to scan (required)
  --exts=LIST   Comma-separated extensions to process
                (default: mp4 mov m4v mkv avi wmv mpg mpeg webm flv ts m2ts 3gp 3g2 ogv)
  --help        Show help
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    build_parser,
    info,
    log,
    require_binary,
    run,
    run_cli,
    scan_root,
    warning,
)

__version__ = "2.1.0"

DEFAULT_EXTS = (
    "mp4",
    "mov",
    "m4v",
    "mkv",
    "avi",
    "wmv",
    "mpg",
    "mpeg",
    "webm",
    "flv",
    "ts",
    "m2ts",
    "3gp",
    "3g2",
    "ogv",
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="remove-metadata",
        description="🧼 Remove all metadata from video files recursively (exiftool).",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    parser.add_argument(
        "--exts",
        default="",
        metavar="LIST",
        help=f"Comma-separated extensions (default: {' '.join(DEFAULT_EXTS)})",
    )
    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    if not args.path:
        warning("❌ --path must be specified")
        parser.print_help()
        return 1

    root = scan_root(args.path)

    require_binary("exiftool", hint="Install exiftool and retry.")

    if args.exts:
        # All whitespace stripped, not just the ends: the shell version used
        # `tr -d '[:space:]'`, so "m p4" became a usable "mp4".
        exts = [re.sub(r"\s+", "", e) for e in args.exts.split(",")]
        exts = [e for e in exts if e]
    else:
        exts = list(DEFAULT_EXTS)

    if not exts:
        warning("❌ No valid extensions provided.")
        return 1

    ext_args: list[str] = []
    for ext in exts:
        ext_args += ["-ext", ext]

    info(f"Removing metadata from extensions: {' '.join(exts)}")
    info(f"Target path: {args.path}")

    # Preview: list the files exiftool will touch. '-i */._*' makes it ignore
    # the AppleDouble sidecars, which otherwise get rewritten pointlessly.
    info("Listing candidate files:")
    run(
        ["exiftool", "-r", "-i", "*/._*", *ext_args, "-q", "-p", "$FilePath", str(root)],
        check=False,
    )

    run(
        [
            "exiftool",
            "-all=",
            "-overwrite_original",
            "-r",
            "-progress",
            "-i",
            "*/._*",
            *ext_args,
            str(root),
        ]
    )

    log("Done.")
    return 0


if __name__ == "__main__":
    run_cli(main)
