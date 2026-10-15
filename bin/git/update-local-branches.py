#!/usr/bin/env python3
"""⬇️  For each local branch with an upstream, rebase onto origin.

Conflicts are aborted and reported; the script keeps going.

Usage:
  update-local-branches.py [--limit=N] [--dry-run]

Options:
  --limit=N    Only update the N most recently committed branches
  --dry-run    List branches that would be updated, change nothing
  --help       Show help
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitutils import (
    current_branch,
    fetch_remotes,
    has_tracked_changes,
    local_branches,
    skip_git_hooks,
    worktree_branch_map,
    worktree_is_clean,
)
from utils import (
    add_bool_flag,
    build_parser,
    heading,
    info,
    log,
    parse_count,
    require_binary,
    run,
    run_cli,
    success,
    warning,
)

__version__ = "3.2.0"


def branches_with_upstream() -> list[str]:
    """Local branches that have an upstream, most recently committed first."""
    return [
        branch for branch, upstream in local_branches("upstream", sort="-committerdate") if upstream
    ]


def rebase(git: list[str]) -> bool:
    """Rebase onto the upstream with ``git`` (plain, or ``-C <worktree>``); abort on failure.

    DELIBERATE DIVERGENCE: the shell version ran ``pull --rebase`` per branch,
    a fetch for every branch on top of the one the run opened with. The remotes
    are fetched once up front, so a bare ``rebase`` (onto ``@{upstream}``, with
    the same fork-point handling ``pull --rebase`` uses) is the whole job.
    """
    if run([*git, "rebase", "--quiet"], check=False).returncode == 0:
        return True
    warning("  ❌ rebase failed — aborting and moving on")
    run([*git, "rebase", "--abort"], check=False, capture=True)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="update-local-branches",
        description="⬇️  Rebase every local branch that has an upstream onto origin.",
    )
    parser.add_argument(
        "--limit",
        default="0",
        metavar="N",
        help="Only update the N most recently committed branches",
    )
    add_bool_flag(
        parser,
        "--dry-run",
        help="List branches that would be updated, change nothing",
    )
    args = parser.parse_args(argv)

    limit = parse_count(args.limit, "--limit")

    require_binary("git")
    skip_git_hooks()

    heading("⬇️   update-local-branches", dry_run=args.dry_run)

    original_branch = current_branch()
    if not original_branch:
        warning("❌ Detached HEAD — check out a branch first.")
        return 1

    # Tracked changes only: an untracked file survives checkout and rebase, and
    # a linked worktree nested in this one is untracked - counting it made
    # sync-all-branches abort right after parking had allowed the same tree.
    if not args.dry_run and has_tracked_changes():
        warning("❌ Working tree is dirty. Commit or stash before running. 🧺")
        return 1

    # Prunes too, where this script's own fetch did not: it shares the one
    # fetch sync-all-branches runs.
    fetch_remotes()

    branches = branches_with_upstream()
    if limit > 0:
        branches = branches[:limit]

    if not branches:
        info("ℹ️  No local branches with upstreams.")  # noqa: RUF001
        return 0

    if args.dry_run:
        info(f"🌵 Would update {len(branches)} branch(es):")
        for branch in branches:
            info(f"  • 🌿 {branch}")
        return 0

    succeeded: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    # Branches checked out in ANOTHER worktree: every pinned one but the branch
    # this worktree has checked out. One `git worktree list` for the whole run,
    # not one per branch as the shell's per-branch `worktree_for_branch` did.
    elsewhere = worktree_branch_map()
    elsewhere.pop(original_branch, None)

    for branch in branches:
        # A branch checked out in another worktree cannot be checked out here —
        # git refuses with "already used by worktree". That's a mechanical
        # limit, not a conflict, so update it in place rather than counting it
        # as a failure.
        if pinned := elsewhere.get(branch):
            # Uncommitted work in a worktree is the user's, left exactly as it
            # is. Skipping it is not a failure, or one worktree in progress
            # would stop every run of sync-all-branches at this step.
            if not worktree_is_clean(pinned):
                warning(f"  ⏭️  {branch} — worktree is dirty ({pinned}), skipping")
                skipped.append(branch)
                continue

            log(f"⬇️  Rebasing {branch} in its worktree ({pinned})")
            git, where = ["git", "-C", pinned], f" (in {pinned})"
        else:
            info(f"📂 Switching to 🌿 {branch}")
            checkout = run(["git", "checkout", "--quiet", branch], check=False, capture=True)
            if checkout.returncode != 0:
                warning("  ✗ checkout failed, skipping")
                failed.append(branch)
                continue

            log(f"⬇️  Rebasing {branch} onto upstream")
            git, where = ["git"], ""

        if rebase(git):
            success(f"  ✅ {branch} up to date{where}")
            succeeded.append(branch)
        else:
            failed.append(branch)

    info(f"🔁 Returning to 🌿 {original_branch}")
    run(["git", "checkout", "--quiet", original_branch])

    print()
    success("═══ summary ═══")
    success(f"✅ Updated: {len(succeeded)}")
    if skipped:
        warning(f"⏭️  Skipped: {len(skipped)} (dirty worktree)")
        for branch in skipped:
            warning(f"  • 🌿 {branch}")
    if failed:
        warning(f"❌ Failed:  {len(failed)}")
        for branch in failed:
            warning(f"  • 💥 {branch}")
        return 1

    success("🎉 All clean!")
    return 0


if __name__ == "__main__":
    run_cli(main)
