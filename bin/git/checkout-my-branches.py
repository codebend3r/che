#!/usr/bin/env python3
"""🌿 Check out recent remote branches authored by you that aren't yet local.

Usage:
  checkout-my-branches.py [--author=EMAIL] [--limit=N]

Options:
  --author=EMAIL   Author email to match (default: git config user.email)
  --limit=N        How many recent remote branches to scan (default: 100)
  --help           Show help
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
    note,
    require_binary,
    run,
    run_cli,
    run_lines,
    run_output,
    success,
    warning,
)

__version__ = "3.0.0"


def main(argv: list[str] | None = None) -> int:
    default_author = run_output(["git", "config", "user.email"], check=False).strip()

    parser = build_parser(
        prog="checkout-my-branches",
        description="🌿 Check out recent remote branches you authored that aren't yet local.",
    )
    parser.add_argument(
        "--author",
        default=default_author,
        metavar="EMAIL",
        help="Author email to match (default: git config user.email)",
    )
    # Kept as a string, not `type=int`: argparse's own int conversion would
    # own the failure and exit before the shell version's message could print.
    parser.add_argument(
        "--limit",
        default="100",
        metavar="N",
        help="How many recent remote branches to scan (default: 100)",
    )
    args = parser.parse_args(argv)

    if not args.author:
        warning("❌ No author email — pass --author=EMAIL or set git config user.email")
        return 1

    if not re.fullmatch(r"[0-9]+", args.limit) or int(args.limit) < 1:
        warning(f"❌ --limit must be a positive integer (got: {args.limit})")
        return 1
    limit = int(args.limit)

    require_binary("git")

    note("═══════════════════════════════════════════")
    note("🌿  checkout-my-branches")
    note("═══════════════════════════════════════════")

    if run_output(["git", "status", "--porcelain"]):
        warning("❌ Working tree is dirty. Commit or stash before running. 🧺")
        return 1

    info("📡 Fetching remotes...")
    run(["git", "fetch", "--all", "--prune", "--quiet"])

    info(f"📦 Scanning {limit} most recent remote branches for author 👤 {args.author}...")

    checked_out = 0
    skipped = 0
    not_mine = 0

    # One pass: author email + refname + symref target, newest first. %(symref)
    # is non-empty for symbolic refs like origin/HEAD, which must be skipped -
    # it is a pointer, not a branch anyone authored.
    #
    # Separator is \x01 rather than the shell version's '|': an author email or
    # a branch name may contain a pipe, and the shell version then mis-split
    # the record. Control characters are illegal in ref names, so \x01 is safe.
    lines = run_lines(
        [
            "git",
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(authoremail)%01%(refname:short)%01%(symref)",
            "refs/remotes/origin",
        ]
    )

    for line in lines[:limit]:
        parts = line.split("\x01")
        if len(parts) < 3:
            continue
        author_email, remote_branch, symref = parts[0], parts[1], parts[2]

        if not remote_branch or symref:
            continue

        author_email = author_email.removeprefix("<").removesuffix(">")
        if author_email != args.author:
            not_mine += 1
            continue

        local_branch = remote_branch.removeprefix("origin/")
        if not local_branch or local_branch == remote_branch:
            continue  # malformed entry — don't touch

        exists = run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{local_branch}"],
            check=False,
            capture=True,
        )
        if exists.returncode == 0:
            info(f"⏭️  Already local: {local_branch}")
            skipped += 1
        else:
            log(f"🆕 Checking out: {local_branch}")
            run(["git", "checkout", "-b", local_branch, "--track", remote_branch])
            checked_out += 1

    print()
    success("═══ summary ═══")
    success(f"🆕  Checked out: {checked_out}")
    success(f"⏭️  Already local: {skipped}")
    success(f"👻  Skipped (not yours): {not_mine}")
    success("✨ Done.")
    return 0


if __name__ == "__main__":
    run_cli(main)
