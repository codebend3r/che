#!/usr/bin/env python3
"""🔐 Show the ownership and mode of a volume under ``/Volumes``.

Usage:
  list-permission.py [VOLUME]   (no VOLUME lists /Volumes itself)

Options:
  --help       Show help
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import build_parser, run, run_cli

__version__ = "1.0.0"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="list-permission",
        description="🔐 Show ownership and mode of a volume under /Volumes.",
    )
    parser.add_argument("volume", nargs="?", default="", help="Volume name (default: /Volumes)")
    # DELIBERATE DIVERGENCE from the shell wrapper, `command ls -ld
    # "/Volumes/$1"`, which ignored any argument after the first. A second one
    # is an error here rather than silently dropped.
    args = parser.parse_args(argv)

    # `ls` runs as a program, so a user's `alias ls=eza` never replaces the
    # `ls -l` listing - the reason the wrapper spelled it `command ls`.
    return run(["ls", "-ld", f"/Volumes/{args.volume}"], check=False).returncode


if __name__ == "__main__":
    run_cli(main)
