#!/usr/bin/env python3
"""🌿 Check out recent remote branches authored by you that aren't yet local.

Each one becomes a local branch tracking its remote. HEAD stays where it is.

Usage:
  checkout-my-branches.py [--author=EMAIL] [--limit=N]

Options:
  --author=EMAIL   Author email to match (default: git config user.email)
  --limit=N        How many recent remote branches to scan (default: 100)
  --help           Show help
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitutils import fetch_remotes, for_each_ref, local_branches, skip_git_hooks
from utils import (
    build_parser,
    heading,
    info,
    log,
    parse_count,
    require_binary,
    run,
    run_cli,
    run_output,
    success,
    warning,
)

__version__ = "3.1.0"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="checkout-my-branches",
        description="🌿 Check out recent remote branches you authored that aren't yet local.",
    )
    parser.add_argument(
        "--author",
        default="",
        metavar="EMAIL",
        help="Author email to match (default: git config user.email)",
    )
    parser.add_argument(
        "--limit",
        default="100",
        metavar="N",
        help="How many recent remote branches to scan (default: 100)",
    )
    args = parser.parse_args(argv)

    limit = parse_count(args.limit, "--limit", minimum=1)

    require_binary("git")
    # Read after the check for git, so a missing git says so rather than
    # reporting that no author email is set.
    author = args.author or run_output(["git", "config", "user.email"], check=False).strip()
    if not author:
        warning("❌ No author email — pass --author=EMAIL or set git config user.email")
        return 1

    # Nothing here checks out, but fetch and branch still fire a repo's
    # reference-transaction hook.
    skip_git_hooks()

    heading("🌿  checkout-my-branches")

    fetch_remotes()

    info(f"📦 Scanning {limit} most recent remote branches for author 👤 {author}...")

    checked_out = 0
    skipped = 0
    not_mine = 0

    local = {branch for (branch,) in local_branches()}

    # One pass: author email + branch name + symref target, newest first.
    # %(symref) is non-empty for symbolic refs like origin/HEAD, which must be
    # skipped - it is a pointer, not a branch anyone authored.
    refs = for_each_ref(
        "refs/remotes/origin",
        "authoremail",
        "refname:lstrip=3",
        "symref",
        sort="-committerdate",
    )

    for author_email, branch, symref in refs[:limit]:
        if symref:
            continue

        if author_email.removeprefix("<").removesuffix(">") != author:
            not_mine += 1
            continue

        if branch in local:
            info(f"⏭️  Already local: {branch}")
            skipped += 1
        else:
            log(f"🆕 Checking out: {branch}")
            # `git branch --track`, not `checkout -b`: switching to each new
            # branch left HEAD on the last one, undoing the park on main that
            # sync-all-branches runs this after. The full ref name cannot be
            # mistaken for a local branch called `origin/<branch>`.
            run(["git", "branch", "--track", branch, f"refs/remotes/origin/{branch}"])
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
