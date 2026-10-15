#!/usr/bin/env python3
"""📊 List the largest files under a path, biggest first.

Usage:
  find-largest-files.py [--path=.] [--length=10] [--full-path]

Options:
  --path=DIR      Directory to scan (default: .)
  --length=N      How many files to list (default: 10)
  --full-path     Print the whole path instead of just the basename
  --help          Show help
"""

from __future__ import annotations

import heapq
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    format_bytes,
    info,
    iter_files,
    note_settings,
    parse_count,
    run_cli,
    scan_root,
)

__version__ = "2.1.0"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="find-largest-files",
        description="📊 List the largest files under a path, biggest first.",
    )
    parser.add_argument("--path", default=".", metavar="DIR", help="Directory to scan (default: .)")
    # A string, validated by parse_count below rather than `type=int`.
    parser.add_argument(
        "--length", default="10", metavar="N", help="How many files to list (default: 10)"
    )
    add_bool_flag(parser, "--full-path", help="Print the whole path")

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    length = parse_count(args.length, "--length")

    note_settings(
        ("Searching in", args.path),
        ("List length", length),
        ("Show full path", args.full_path),
        rule=False,
    )

    # An empty --path reads "--path is required" after the settings, where the
    # shell version printed "--path cannot be empty" before them.
    root = scan_root(args.path)

    def sized() -> Iterator[tuple[int, str, Path]]:
        for path in iter_files(root, skip_macos_metadata=False):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            # The shell pipeline (find | xargs stat | sort) broke on any
            # filename containing its '|' separator. Sizing in-process removes
            # that failure mode entirely.
            yield size, str(path), path

    # `sort -nr | head -n N` ties break on the whole line DESCENDING, because
    # -r reverses the last-resort comparison too. nlargest on (size, str, ...)
    # gives the same ordering - the path string is unique, so the comparison
    # never reaches the Path - and holds only N entries rather than the whole
    # tree: a million-file media root would otherwise cost about a gigabyte.
    top = heapq.nlargest(length, sized())

    for size, _, path in top:
        if args.full_path:
            # Rebuild from the user's own --path string so a default of "."
            # still prints "./name", as `find .` did. Path() would normalise
            # the "./" away and break anything piping this into xargs.
            label = f"{args.path.rstrip('/')}/{path.relative_to(root)}"
        else:
            label = path.name
        print(f"{format_bytes(size):>12}  {label}", flush=True)

    return 0


if __name__ == "__main__":
    run_cli(main)
