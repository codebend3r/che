#!/usr/bin/env python3
"""💣 Check out every local branch and hard reset it to origin/<branch>.

Fetch once, then for each local branch that has an origin/<branch> and differs
from it: check it out and ``git reset --hard`` to the origin state. A branch
checked out in another worktree is reset inside that worktree instead. Local
commits are dropped (they stay in the reflog); untracked files are left alone.
Returns to the starting branch at the end.

Uncommitted changes to tracked files are never discarded without --force:
the current worktree refuses to start, another dirty worktree is skipped.

Usage:
  hard-reset-all-branches.py [--dry-run] [--force]

Options:
  --dry-run    Show what would be reset and what it would drop, change nothing
  --force      Also discard uncommitted changes to tracked files
  --help       Show help

Env:
  DRY_RUN=true Same as --dry-run (used by the shell -dr wrapper)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitutils import (
    current_branch,
    fetch_remotes,
    for_each_ref,
    has_tracked_changes,
    in_progress,
    local_branches,
    skip_git_hooks,
    worktree_branch_map,
)
from report import FAIL, NOTE, OK, PLAN, SAME, WARN, Listing, Outcome, Tally, duration, plural
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
    run_output,
    warning,
)

__version__ = "2.0.0"


class Reset(Outcome):
    """Everything a hard reset can conclude about a branch, in summary order."""

    RESET = (OK, "reset", "Reset to origin")
    WOULD_RESET = (PLAN, "would reset", "Would reset")
    CURRENT = (SAME, "", "Already match", Listing.COUNT)
    NO_ORIGIN = (NOTE, "", "No origin, left alone")
    SKIPPED = (WARN, "skipped", "Skipped")
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


def origin_names(cwd: Path) -> set[str]:
    """Branch names under ``refs/remotes/origin/``, minus the ``HEAD`` symref."""
    return {
        branch
        for branch, symref in for_each_ref(
            "refs/remotes/origin/", "refname:lstrip=3", "symref", cwd=cwd
        )
        if not symref
    }


def divergence(branch: str, cwd: Path) -> tuple[int, int]:
    """``(local-only commits, origin-only commits)`` between ``branch`` and origin.

    Full refs throughout, so a tag named like the branch cannot be picked instead.
    """
    counts = run_output(
        [
            "git",
            "rev-list",
            "--left-right",
            "--count",
            f"refs/heads/{branch}...refs/remotes/origin/{branch}",
        ],
        cwd=cwd,
    ).split()
    return int(counts[0]), int(counts[1])


def describe(ahead: int, behind: int) -> str:
    parts = []
    if ahead:
        parts.append(f"drops {plural(ahead, 'local commit')}")
    if behind:
        parts.append(f"picks up {behind} from origin")
    return ", ".join(parts)


def reset_one(
    tally: Tally[Reset],
    root: Path,
    branch: str,
    detail: str,
    pinned: str | None,
    force: bool,
) -> None:
    """Hard reset ``branch`` to origin, here or in the worktree that holds it."""

    def skip(reason: str) -> None:
        tally.record(Reset.SKIPPED, branch, reason, item=f"{branch}: {reason}")

    def fail(reason: str) -> None:
        tally.record(Reset.FAILED, branch, reason, item=f"{branch}: {reason}")

    if pinned:
        path = Path(pinned)
        if in_progress(path):
            skip(f"operation in progress in {pinned}")
            return
        # Uncommitted work in another worktree is the user's; only --force
        # may throw it away.
        if has_tracked_changes(path) and not force:
            skip(f"dirty worktree {pinned}")
            return
        git, where = ["git", "-C", pinned], f"in {pinned}; "
    else:
        checkout = ["git", "checkout", "--quiet", *(["--force"] if force else []), branch]
        if run(checkout, check=False, capture=True, cwd=root).returncode != 0:
            fail("checkout failed")
            return
        git, where = ["git", "-C", str(root)], ""

    before = run_output([*git, "rev-parse", "--short", "HEAD"])
    completed = run(
        [*git, "reset", "--hard", "--quiet", f"refs/remotes/origin/{branch}"],
        check=False,
        capture=True,
    )
    if completed.returncode != 0:
        fail(f"reset failed: {(completed.stderr or '').strip()}")
        return
    tally.record(Reset.RESET, branch, f"{where}was {before}; {detail}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="hard-reset-all-branches",
        description="💣 Check out every local branch and hard reset it to origin/<branch>.",
    )
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", True),
        help="Show what would be reset and what it would drop, change nothing",
    )
    add_bool_flag(
        parser,
        "--force",
        help="Also discard uncommitted changes to tracked files",
    )
    args = parser.parse_args(argv)
    started = time.monotonic()

    require_binary("git")
    skip_git_hooks()

    heading("💣  hard-reset-all-branches", dry_run=args.dry_run)

    if run_output(["git", "rev-parse", "--is-inside-work-tree"], check=False) != "true":
        warning("❌ Not inside a git working tree.")
        return 1
    root = Path(run_output(["git", "rev-parse", "--show-toplevel"]))

    original = current_branch(root)
    if not original:
        warning("❌ Detached HEAD: check out a branch first.")
        return 1

    if in_progress(root):
        warning("❌ A rebase, merge or similar is in progress here; finish or abort it first.")
        return 1

    if has_tracked_changes(root) and not args.force:
        if not args.dry_run:
            warning("❌ Working tree is dirty. Commit, stash or pass --force to discard. 🧺")
            return 1
        warning("⚠️  Working tree is dirty: a real run refuses without --force.")

    if not args.dry_run:
        info(f"📍 Returning to {original} at the end")
    # Fetched in a dry run too: the preview is only worth reading if it
    # compares against what origin holds now. A fetch touches no local branch.
    fetch_remotes()

    # Branches checked out in ANOTHER worktree cannot be checked out here, so
    # they are reset where they are. The current branch is not among them: it
    # is checked out (a no-op) and reset like the rest.
    elsewhere = worktree_branch_map(root)
    elsewhere.pop(original, None)

    tally = Tally(Reset)
    remote = origin_names(root)
    branches = [branch for (branch,) in local_branches(cwd=root)]
    with tally.progress(len(branches)) as progress:
        for branch in branches:
            progress.step(branch)
            if branch not in remote:
                tally.record(Reset.NO_ORIGIN, branch)
                continue
            ahead, behind = divergence(branch, root)
            if not (ahead or behind):
                tally.record(Reset.CURRENT, branch)
                continue
            detail = describe(ahead, behind)
            pinned = elsewhere.get(branch)
            if args.dry_run:
                where = f"in {pinned}; " if pinned else ""
                tally.record(Reset.WOULD_RESET, branch, f"{where}{detail}")
                continue
            reset_one(tally, root, branch, detail, pinned, args.force)

    if not args.dry_run:
        run(["git", "checkout", "--quiet", original], cwd=root)

    notes = []
    if tally.count(Reset.RESET):
        notes.append("Dropped commits stay reachable for a while: git reflog show <branch>")
    notes.append("Untracked files are never touched. Nothing pushed.")
    tally.summary(
        "Preview" if args.dry_run else "Summary",
        facts=[plural(len(branches), "branch", "branches"), duration(time.monotonic() - started)],
        notes=notes,
    )
    print()
    if count := tally.count(Reset.FAILED):
        warning(
            f"⚠️  {plural(count, 'branch', 'branches')} failed. Every other branch was still attempted."
        )
        return 1
    if args.dry_run:
        dry_run_complete("reset")
    else:
        log("🎉 Reset complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
