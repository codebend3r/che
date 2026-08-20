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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    format_bytes,
    info,
    iter_files,
    note,
    run_cli,
    scan_root,
    warning,
)

__version__ = "2.0.4"

_NON_NEGATIVE_INT = re.compile(r"[0-9]+")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="find-largest-files",
        description="📊 List the largest files under a path, biggest first.",
    )
    parser.add_argument("--path", default=".", metavar="DIR", help="Directory to scan (default: .)")
    # Kept as a string, not `type=int`: argparse's int conversion would own the
    # error and exit before the shell version's own message could be produced.
    parser.add_argument(
        "--length", default="10", metavar="N", help="How many files to list (default: 10)"
    )
    add_bool_flag(parser, "--full-path", dest="full_path", help="Print the whole path")

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    if not _NON_NEGATIVE_INT.fullmatch(args.length):
        warning("❌ --length must be a non-negative integer")
        return 1
    length = int(args.length)

    if not args.path:
        warning("❌ --path cannot be empty")
        return 1

    note(f"Searching in: {args.path}")
    note(f"List length: {length}")
    note(f"Show full path: {str(args.full_path).lower()}")

    root = scan_root(args.path)

    def sized() -> list[tuple[int, str, Path]]:
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
    # -r reverses the last-resort comparison too. nlargest on (size, str) gives
    # the same ordering, and holds only N entries rather than the whole tree -
    # a million-file media root would otherwise cost about a gigabyte.
    top = heapq.nlargest(length, sized(), key=lambda item: (item[0], item[1]))

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
