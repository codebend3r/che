#!/usr/bin/env python3
"""🎞️  Find movie folders whose name ends with a given year, e.g. "Alien (1979)".

Usage:
  find-movie-by-year.py --year=YYYY [--path=/path/to/search]

Options:
  --year=YYYY   Year to match. Glob metacharacters work, so --year='2*'
                matches any year starting with 2 (required)
  --path=DIR    Directory to search (default: .)
  --help        Show help
"""

from __future__ import annotations

import os
import sys
from fnmatch import fnmatchcase
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import build_parser, info, run_cli, scan_root, warning

__version__ = "3.0.0"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="find-movie-by-year",
        description='🎞️  Find movie folders whose name ends with "(YYYY)".',
        epilog="Example: find-movie-by-year.py --year=2025 --path=/movies",
    )
    parser.add_argument("--year", default="", metavar="YYYY", help="Year to match (required)")
    parser.add_argument(
        "--path", default=".", metavar="DIR", help="Directory to search (default: .)"
    )

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    if not args.year:
        warning("❌ --year is required")
        return 1

    root = scan_root(args.path)

    # `find -type d -iname "*(YYYY)"` - a folder name ENDING in the
    # parenthesised year, matched case-insensitively. fnmatch rather than a
    # plain endswith so glob metacharacters in --year still work, as they did
    # when the value was interpolated straight into the -iname pattern.
    pattern = f"*({args.year.lower()})"

    def emit(path: Path) -> None:
        # `find <dir>` prints paths prefixed with the start directory exactly as
        # the user spelled it, including a leading "./" for the default. pathlib
        # collapses "." away, so join the raw string instead - anything piping
        # this into xargs depends on that prefix.
        if path == root:
            print(args.path, flush=True)
        else:
            # os.path.join, not Path: Path would normalise a leading './'
            # away, and that prefix is exactly what has to survive.
            print(os.path.join(args.path, str(path.relative_to(root))), flush=True)  # noqa: PTH118

    # `find` includes the start directory in its results.
    if fnmatchcase(root.name.lower(), pattern):
        emit(root)

    # Results are sorted for reproducibility; `find` emitted readdir order.
    for dirpath, dirnames, _ in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in dirnames:
            child = Path(dirpath) / name
            if child.is_symlink():
                continue
            if fnmatchcase(name.lower(), pattern):
                emit(child)

    return 0


if __name__ == "__main__":
    run_cli(main)
