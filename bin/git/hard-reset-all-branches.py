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
    success,
    warning,
)

__version__ = "1.0.0"


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
        parts.append(f"drops {ahead} local commit(s)")
    if behind:
        parts.append(f"picks up {behind} from origin")
    return ", ".join(parts)


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

    require_binary("git")
    skip_git_hooks()

    heading("💣  hard-reset-all-branches", dry_run=args.dry_run)

    if run_output(["git", "rev-parse", "--is-inside-work-tree"], check=False) != "true":
        warning("❌ Not inside a git working tree.")
        return 1
    root = Path(run_output(["git", "rev-parse", "--show-toplevel"]))

    original = current_branch(root)
    if not original:
        warning("❌ Detached HEAD — check out a branch first.")
        return 1

    if in_progress(root):
        warning("❌ A rebase, merge or similar is in progress here — finish or abort it first.")
        return 1

    if has_tracked_changes(root) and not args.force:
        if not args.dry_run:
            warning("❌ Working tree is dirty. Commit, stash or pass --force to discard. 🧺")
            return 1
        warning("⚠️  Working tree is dirty: a real run refuses without --force.")

    # Fetched in a dry run too: the preview is only worth reading if it
    # compares against what origin holds now. A fetch touches no local branch.
    fetch_remotes()

    remote = origin_names(root)
    no_origin: list[str] = []
    in_sync: list[str] = []
    targets: list[tuple[str, int, int]] = []
    for (branch,) in local_branches(cwd=root):
        if branch not in remote:
            no_origin.append(branch)
            continue
        ahead, behind = divergence(branch, root)
        if ahead or behind:
            targets.append((branch, ahead, behind))
        else:
            in_sync.append(branch)

    if no_origin:
        info(f"⏭️  {len(no_origin)} branch(es) have no origin/<branch>, left alone:")
        for branch in no_origin:
            info(f"  • 🌿 {branch}")

    if not targets:
        success(f"✨ All {len(in_sync)} branch(es) with an origin already match it. 🎉")
        return 0

    # Branches checked out in ANOTHER worktree cannot be checked out here, so
    # they are reset where they are. The current branch is not among them: it
    # is checked out (a no-op) and reset like the rest.
    elsewhere = worktree_branch_map(root)
    elsewhere.pop(original, None)

    if args.dry_run:
        warning(f"🌵 {len(targets)} branch(es) would be hard reset to origin:")
        for branch, ahead, behind in targets:
            where = f" (in {elsewhere[branch]})" if branch in elsewhere else ""
            warning(f"  • 💣 {branch}{where} — {describe(ahead, behind)}")
        dry_run_complete("reset")
        return 0

    reset: list[str] = []
    skipped: list[tuple[str, str]] = []
    failed: list[str] = []
    checkout = ["git", "checkout", "--quiet", *(["--force"] if args.force else [])]

    for branch, ahead, behind in targets:
        if pinned := elsewhere.get(branch):
            path = Path(pinned)
            if in_progress(path):
                warning(f"  ⏭️  {branch} — operation in progress in {pinned}, skipping")
                skipped.append((branch, "operation in progress"))
                continue
            # Uncommitted work in another worktree is the user's; only --force
            # may throw it away.
            if has_tracked_changes(path) and not args.force:
                warning(f"  ⏭️  {branch} — worktree is dirty ({pinned}), skipping")
                skipped.append((branch, "dirty worktree"))
                continue
            log(f"💣 Resetting {branch} in its worktree ({pinned})")
            git, where = ["git", "-C", pinned], f" (in {pinned})"
        else:
            info(f"📂 Switching to 🌿 {branch}")
            if run([*checkout, branch], check=False, capture=True, cwd=root).returncode != 0:
                warning("  ✗ checkout failed, skipping")
                failed.append(branch)
                continue
            log(f"💣 Resetting {branch} to origin/{branch}")
            git, where = ["git", "-C", str(root)], ""

        before = run_output([*git, "rev-parse", "--short", "HEAD"])
        completed = run(
            [*git, "reset", "--hard", "--quiet", f"refs/remotes/origin/{branch}"],
            check=False,
            capture=True,
        )
        if completed.returncode != 0:
            warning(f"  ❌ reset failed: {(completed.stderr or '').strip()}")
            failed.append(branch)
            continue
        success(f"  ✅ {branch} matches origin{where} (was {before}; {describe(ahead, behind)})")
        reset.append(branch)

    info(f"🔁 Returning to 🌿 {original}")
    run(["git", "checkout", "--quiet", original], cwd=root)

    print()
    success("═══ summary ═══")
    success(f"✅ Reset:    {len(reset)}")
    if in_sync:
        success(f"✨ In sync:  {len(in_sync)}")
    if reset:
        info("💡 Dropped commits stay reachable for a while: git reflog show <branch>")
    if skipped:
        warning(f"⏭️  Skipped:  {len(skipped)}")
        for branch, reason in skipped:
            warning(f"  • 🌿 {branch} ({reason})")
    if failed:
        warning(f"❌ Failed:   {len(failed)}")
        for branch in failed:
            warning(f"  • 💥 {branch}")
        return 1

    success("🎉 All clean!")
    return 0


if __name__ == "__main__":
    run_cli(main)
