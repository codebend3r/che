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
import time
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
from report import FAIL, OK, PLAN, SAME, WARN, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    dry_run_complete,
    heading,
    info,
    log,
    parse_count,
    require_binary,
    run,
    run_cli,
    run_output,
    warning,
)

__version__ = "4.0.0"


class Update(Outcome):
    """Everything an update can conclude about a branch, in summary order."""

    UPDATED = (OK, "updated", "Updated")
    WOULD_UPDATE = (PLAN, "would update", "Would update")
    CURRENT = (SAME, "", "Already up to date", Listing.COUNT)
    SKIPPED = (WARN, "skipped", "Skipped")
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


def branches_with_upstream() -> dict[str, str]:
    """Each local branch that has an upstream, mapped to that upstream's full
    ref, most recently committed first."""
    return {
        branch: upstream
        for branch, upstream in local_branches("upstream", sort="-committerdate")
        if upstream
    }


def behind(branch: str, upstream: str) -> int:
    """How many commits ``upstream`` has that ``branch`` lacks.

    Spelled ``refs/heads/``, so a tag named like the branch cannot stand in.
    """
    count = run_output(
        ["git", "rev-list", "--count", f"refs/heads/{branch}..{upstream}"], check=False
    )
    return int(count) if count.isdigit() else 0


def rebase(git: list[str]) -> bool:
    """Rebase onto the upstream with ``git`` (plain, or ``-C <worktree>``); abort on failure.

    DELIBERATE DIVERGENCE: the shell version ran ``pull --rebase`` per branch,
    a fetch for every branch on top of the one the run opened with. The remotes
    are fetched once up front, so a bare ``rebase`` (onto ``@{upstream}``, with
    the same fork-point handling ``pull --rebase`` uses) is the whole job.
    """
    if run([*git, "rebase", "--quiet"], check=False, capture=True).returncode == 0:
        return True
    run([*git, "rebase", "--abort"], check=False, capture=True)
    return False


def update_one(tally: Tally[Update], branch: str, pinned: str | None) -> None:
    """Rebase ``branch`` onto its upstream, here or in the worktree that holds it."""
    if pinned:
        # Uncommitted work in a worktree is the user's, left exactly as it
        # is. Skipping it is not a failure, or one worktree in progress
        # would stop every run of sync-all-branches at this step.
        if not worktree_is_clean(pinned):
            reason = f"dirty worktree {pinned}"
            tally.record(Update.SKIPPED, branch, reason, item=f"{branch}: {reason}")
            return
        git, where = ["git", "-C", pinned], f"in {pinned}; "
    else:
        checkout = run(["git", "checkout", "--quiet", branch], check=False, capture=True)
        if checkout.returncode != 0:
            tally.record(
                Update.FAILED, branch, "checkout failed", item=f"{branch}: checkout failed"
            )
            return
        git, where = ["git"], ""

    before = run_output([*git, "rev-parse", "HEAD"])
    if not rebase(git):
        reason = "rebase failed, aborted"
        tally.record(Update.FAILED, branch, reason, item=f"{branch}: {reason}")
        return
    after = run_output([*git, "rev-parse", "HEAD"])
    if after == before:
        tally.record(Update.CURRENT, branch)
    else:
        tally.record(Update.UPDATED, branch, f"{where}was {before[:7]}, now {after[:7]}")


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
    started = time.monotonic()

    limit = parse_count(args.limit, "--limit")

    require_binary("git")
    skip_git_hooks()

    heading("⬇️   update-local-branches", dry_run=args.dry_run)

    original_branch = current_branch()
    if not original_branch:
        warning("❌ Detached HEAD: check out a branch first.")
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

    upstreams = branches_with_upstream()
    branches = list(upstreams)
    if limit > 0:
        branches = branches[:limit]

    if not branches:
        info("ℹ️  No local branches with upstreams.")  # noqa: RUF001
        return 0

    if not args.dry_run:
        info(f"📍 Returning to {original_branch} at the end")

    # Branches checked out in ANOTHER worktree: every pinned one but the branch
    # this worktree has checked out. One `git worktree list` for the whole run,
    # not one per branch as the shell's per-branch `worktree_for_branch` did.
    elsewhere = worktree_branch_map()
    elsewhere.pop(original_branch, None)

    tally = Tally(Update)
    with tally.progress(len(branches)) as progress:
        for branch in branches:
            progress.step(branch)
            # A branch checked out in another worktree cannot be checked out
            # here: git refuses with "already used by worktree". That's a
            # mechanical limit, not a conflict, so update it in place rather
            # than counting it as a failure.
            pinned = elsewhere.get(branch)
            if args.dry_run:
                if count := behind(branch, upstreams[branch]):
                    where = f"in {pinned}; " if pinned else ""
                    tally.record(Update.WOULD_UPDATE, branch, f"{where}{count} behind upstream")
                else:
                    tally.record(Update.CURRENT, branch)
                continue
            update_one(tally, branch, pinned)

    if not args.dry_run:
        run(["git", "checkout", "--quiet", original_branch])

    tally.summary(
        "Preview" if args.dry_run else "Summary",
        facts=[plural(len(branches), "branch", "branches"), duration(time.monotonic() - started)],
        notes=["Nothing pushed."],
    )
    print()
    if count := tally.count(Update.FAILED):
        warning(
            f"⚠️  {plural(count, 'branch', 'branches')} failed. Every other branch was still attempted."
        )
        return 1
    if args.dry_run:
        dry_run_complete("updated")
    else:
        log("🎉 Update complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
