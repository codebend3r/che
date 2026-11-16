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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitutils import fetch_remotes, local_branches, skip_git_hooks, worktree_branch_map
from report import NOTE, OK, PLAN, SAME, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    dry_run_complete,
    env_bool,
    heading,
    info,
    log,
    require_binary,
    run,
    run_cli,
)

__version__ = "4.0.0"

DEFAULT_PROTECTED = ("main", "master", "dev", "develop", "staging")


class Clean(Outcome):
    """Everything a cleanup can conclude about a local branch, in summary order."""

    DELETED = (OK, "deleted", "Deleted")
    WOULD_DELETE = (PLAN, "would delete", "Would delete")
    LEFT_ALONE = (SAME, "", "Not stale or protected", Listing.COUNT)
    CHECKED_OUT = (NOTE, "checked out", "Stale, checked out", Listing.ALL)


def is_stale(branch: str, track: str, protected: set[str]) -> bool:
    """Whether ``branch``'s upstream is marked ``[gone]`` and it is not protected.

    ``[gone]`` means the remote branch was deleted, which is what a merged and
    tidied-up PR leaves behind. It does *not* mean merged: a closed-unmerged
    PR looks identical here, same as in the shell version.

    The current branch gets no special case: its worktree pins it like any
    other checked-out branch, so ``main`` reports it alongside those.
    """
    return branch not in protected and "[gone]" in track


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
    started = time.monotonic()

    require_binary("git")
    skip_git_hooks()

    protected = set(DEFAULT_PROTECTED)
    protected.update(name for name in args.protect.split(",") if name)

    heading("🧹  clean-stale-branches", dry_run=args.dry_run)

    fetch_remotes()

    info("🔍 Scanning local branches for gone upstreams...")
    branches = local_branches("upstream:track")

    # A branch checked out in a worktree cannot be deleted: git refuses with
    # "already used by worktree". Those are reported rather than aborting the
    # whole run. Worktrees are the user's, so they are left alone, never
    # removed to free the branch.
    # One `git worktree list` for the whole set, not one per branch as the
    # shell's per-branch `worktree_for_branch` did.
    pinned_by_branch = worktree_branch_map()

    tally = Tally(Clean)
    with tally.progress(len(branches)) as progress:
        for branch, track in branches:
            progress.step(branch)
            if not is_stale(branch, track, protected):
                tally.record(Clean.LEFT_ALONE, branch)
            elif pinned := pinned_by_branch.get(branch):
                tally.record(
                    Clean.CHECKED_OUT, branch, f"in {pinned}", item=f"{branch}: in {pinned}"
                )
            elif args.dry_run:
                tally.record(Clean.WOULD_DELETE, branch, "upstream gone")
            else:
                run(["git", "branch", "-D", branch], capture=True)
                tally.record(Clean.DELETED, branch, "upstream gone")

    notes = []
    if tally.count(Clean.CHECKED_OUT):
        notes.append(
            "Switch off or remove those worktrees, and the next run deletes their branches."
        )
    tally.summary(
        "Preview" if args.dry_run else "Summary",
        facts=[plural(len(branches), "branch", "branches"), duration(time.monotonic() - started)],
        notes=notes,
    )
    print()
    if args.dry_run:
        dry_run_complete("deleted")
    else:
        log("🎉 Cleanup complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
