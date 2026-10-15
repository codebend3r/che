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

from media import LIBRARY_EXTENSIONS
from utils import (
    CYAN,
    GREEN,
    YELLOW,
    add_bool_flag,
    build_parser,
    format_bytes,
    info,
    iter_files,
    log,
    note_settings,
    paint,
    run_cli,
    scan_root,
)

__version__ = "3.1.0"

SORT_METHODS = ("alpha", "fileSizeAsc", "fileSizeDesc")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="video-list",
        description="🎬 List .mp4/.mkv files under a path with human-readable sizes.",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    add_bool_flag(parser, "--recursive", help="Recurse into subdirectories")
    add_bool_flag(parser, "--with-folder", help="Prefix with folder name")
    parser.add_argument(
        "--sort",
        default="alpha",
        choices=SORT_METHODS,
        metavar="METHOD",
        help="alpha (default), fileSizeAsc, or fileSizeDesc",
    )
    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    note_settings(
        ("Scanning", args.path),
        ("Recursive", args.recursive),
        ("Sort method", args.sort),
        ("With folder", args.with_folder),
    )

    # Replaces the shell version's `find` error on a missing path with a
    # styled message; the exit code is unchanged.
    root = scan_root(args.path)

    entries: list[tuple[int, Path]] = []
    for path in iter_files(
        root,
        extensions=LIBRARY_EXTENSIONS,
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

    # DELIBERATE DIVERGENCE: the shell version baked these escapes into every
    # line unconditionally, so NO_COLOR or a pipe still got them raw. paint()
    # honours both, like every other coloured line in the repo.
    for size, path in entries:
        display = f"{paint(path.name, GREEN)} {paint(f'[{format_bytes(size)}]', YELLOW)}"
        if args.with_folder:
            # `basename $(dirname ./x.mkv)` is ".", but pathlib collapses the
            # "." away and leaves parent.name empty - which would render as a
            # bare leading slash and read like an absolute path.
            folder = path.parent.name or path.parent.as_posix()
            display = f"{paint(folder, CYAN)}/{display}"
        log(display)

    return 0


if __name__ == "__main__":
    run_cli(main)
