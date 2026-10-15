#!/usr/bin/env python3
"""🧹 Delete local branches whose upstream is gone (the remote branch was deleted).

Protected branches are never deleted, and neither is a branch checked out in a
worktree - the current one included. Those are reported instead.

Usage:
  clean-stale-branches.py [--dry-run] [--protect=BRANCH1,BRANCH2,...]

Options:
  --dry-run        Show what would be deleted, change nothing
  --protect=LIST   Comma-separated extra branches to protect
                   (defaults: main master dev develop staging)
  --help           Show help

Env:
  DRY_RUN=true     Same as --dry-run (used by the .zshrc -dr wrapper)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitutils import fetch_remotes, local_branches, skip_git_hooks, worktree_branch_map
from utils import (
    add_bool_flag,
    build_parser,
    dry_run_complete,
    env_bool,
    heading,
    info,
    require_binary,
    run,
    run_cli,
    success,
    warning,
)

__version__ = "3.2.0"

DEFAULT_PROTECTED = ("main", "master", "dev", "develop", "staging")


def stale_branches(protected: set[str]) -> list[str]:
    """Local branches whose upstream is marked ``[gone]``.

    ``[gone]`` means the remote branch was deleted, which is what a merged and
    tidied-up PR leaves behind. It does *not* mean merged - a closed-unmerged
    PR looks identical here, same as in the shell version.

    The current branch gets no special case: its worktree pins it like any
    other checked-out branch, so ``main`` reports it alongside those.
    """
    return [
        branch
        for branch, track in local_branches("upstream:track")
        if branch not in protected and "[gone]" in track
    ]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="clean-stale-branches",
        description="🧹 Delete local branches whose upstream is gone.",
    )
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", False),
        help="Show what would be deleted, change nothing",
    )
    parser.add_argument(
        "--protect",
        default="",
        metavar="LIST",
        help=f"Comma-separated extra branches to protect (defaults: {' '.join(DEFAULT_PROTECTED)})",
    )
    args = parser.parse_args(argv)

    require_binary("git")
    skip_git_hooks()

    protected = set(DEFAULT_PROTECTED)
    protected.update(name for name in args.protect.split(",") if name)

    heading("🧹  clean-stale-branches", dry_run=args.dry_run)

    fetch_remotes()

    info("🔍 Scanning local branches for gone upstreams...")
    stale = stale_branches(protected)

    if not stale:
        success("✨ No stale branches. All clean! 🎉")
        return 0

    # A branch checked out in a worktree cannot be deleted — git refuses with
    # "already used by worktree". Split those out so one pinned branch doesn't
    # abort the whole run. Worktrees are the user's, so they are reported and
    # left alone, never removed to free the branch.
    # One `git worktree list` for the whole set, not one per branch as the
    # shell's per-branch `worktree_for_branch` did.
    pinned_by_branch = worktree_branch_map()
    deletable = [branch for branch in stale if branch not in pinned_by_branch]
    pinned = [(branch, pinned_by_branch[branch]) for branch in stale if branch in pinned_by_branch]

    if pinned:
        warning(f"⏭️  {len(pinned)} stale branch(es) are checked out in a worktree:")
        for branch, path in pinned:
            warning(f"  • 🌿 {branch} (in {path})")
        info("💡 Switch off or remove those worktrees, and the next run deletes their branches.")

    if not deletable:
        success("✨ Nothing left to delete. 🎉")
        return 0

    if args.dry_run:
        warning(f"🌵 {len(deletable)} stale branch(es) would be deleted:")
        for branch in deletable:
            warning(f"  • 🪦 {branch}")
        dry_run_complete("deleted")
        return 0

    for branch in deletable:
        warning(f"🗑️  Deleting: {branch}")
        run(["git", "branch", "-D", branch])

    success(f"✨ Removed {len(deletable)} stale branch(es). 🎉")
    return 0


if __name__ == "__main__":
    run_cli(main)
