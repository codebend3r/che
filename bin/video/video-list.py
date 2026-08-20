#!/usr/bin/env python3
"""🎬 List .mp4/.mkv files under a path with human-readable sizes.

Usage:
  video-list.py --path=/dir [--recursive] [--sort=alpha|fileSizeAsc|fileSizeDesc]
                [--with-folder]

Options:
  --path=DIR      Directory to scan (required)
  --recursive     Recurse into subdirectories (default: top level only)
  --sort=METHOD   alpha (default), fileSizeAsc, or fileSizeDesc
  --with-folder   Prefix each name with its containing folder
  --help          Show help
"""

from __future__ import annotations

import locale
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    CYAN,
    GREEN,
    NC,
    YELLOW,
    add_bool_flag,
    build_parser,
    format_bytes,
    info,
    iter_files,
    log,
    note,
    run_cli,
    scan_root,
    warning,
)

__version__ = "3.0.0"

VIDEO_EXTENSIONS = ("mp4", "mkv")
SORT_METHODS = ("alpha", "fileSizeAsc", "fileSizeDesc")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="video-list",
        description="🎬 List .mp4/.mkv files under a path with human-readable sizes.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    add_bool_flag(parser, "--recursive", help="Recurse into subdirectories")
    add_bool_flag(parser, "--with-folder", dest="with_folder", help="Prefix with folder name")
    parser.add_argument(
        "--sort",
        default="alpha",
        choices=SORT_METHODS,
        metavar="METHOD",
        help="alpha (default), fileSizeAsc, or fileSizeDesc",
    )
    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    note(f"Scanning: {args.path}")
    note(f"Recursive: {str(args.recursive).lower()}")
    note(f"Sort method: {args.sort}")
    note(f"With folder: {str(args.with_folder).lower()}")
    note("----------------------------------------------------")

    if not args.path:
        warning("❌ --path is required")
        return 1

    # Replaces the shell version's `find` error on a missing path with a
    # styled message; the exit code is unchanged.
    root = scan_root(args.path)

    entries: list[tuple[int, Path]] = []
    for path in iter_files(
        root,
        extensions=VIDEO_EXTENSIONS,
        recursive=args.recursive,
        skip_hidden=True,
    ):
        try:
            entries.append((path.stat().st_size, path))
        except OSError:
            continue

    if args.sort == "fileSizeAsc":
        entries.sort(key=lambda item: (item[0], str(item[1])))
    elif args.sort == "fileSizeDesc":
        # `sort -nr` reverses its last-resort full-line tiebreak too, so equal
        # sizes come out in DESCENDING path order. Reverse both key fields.
        entries.sort(key=lambda item: (item[0], str(item[1])), reverse=True)
    else:
        # `sort -k2` collates under LC_COLLATE, which is case-insensitive at
        # the primary level. strxfrm reproduces that; a plain codepoint sort
        # would put every capitalised name first.
        locale.setlocale(locale.LC_COLLATE, "")
        entries.sort(key=lambda item: locale.strxfrm(str(item[1])))

    for size, path in entries:
        size_human = format_bytes(size)
        if args.with_folder:
            # `basename $(dirname ./x.mkv)` is ".", but pathlib collapses the
            # "." away and leaves parent.name empty - which would render as a
            # bare leading slash and read like an absolute path.
            folder = path.parent.name or path.parent.as_posix()
            display = f"{CYAN}{folder}{NC}/{GREEN}{path.name}{NC} {YELLOW}[{size_human}]{NC}"
        else:
            display = f"{GREEN}{path.name}{NC} {YELLOW}[{size_human}]{NC}"
        log(display)

    return 0


if __name__ == "__main__":
    run_cli(main)
