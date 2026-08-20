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

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
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
    worktree_branch_map,
    worktree_is_clean,
)

__version__ = "3.1.0"


def branches_with_upstream() -> list[str]:
    """Local branches that have an upstream, most recently committed first.

    The separator is \\x01, not the shell version's ``|``. A branch name may
    legally contain a pipe (``git check-ref-format`` allows it), and splitting
    on ``|`` then treating the whole remainder as the upstream reports such a
    branch as *having* an upstream when it does not - after which
    ``git pull --rebase`` fails on it and the run exits non-zero. Control
    characters are illegal in ref names, so \\x01 cannot collide.
    """
    found = []
    for line in run_lines(
        [
            "git",
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname:short)%01%(upstream)",
            "refs/heads/",
        ]
    ):
        branch, _, upstream = line.partition("\x01")
        if branch and upstream:
            found.append(branch)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="update-local-branches",
        description="⬇️  Rebase every local branch that has an upstream onto origin.",
    )
    # Kept as a string, not `type=int`: argparse's own int conversion would
    # own the failure and exit before the shell version's message could print.
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

    if not re.fullmatch(r"[0-9]+", args.limit):
        warning(f"❌ --limit must be a non-negative integer (got: {args.limit})")
        return 1
    limit = int(args.limit)

    require_binary("git")

    header_suffix = " 🌵 (dry run)" if args.dry_run else ""
    note("═══════════════════════════════════════════")
    note(f"⬇️   update-local-branches{header_suffix}")
    note("═══════════════════════════════════════════")

    original_branch = run_output(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"], check=False
    ).strip()
    if not original_branch:
        warning("❌ Detached HEAD — check out a branch first.")
        return 1

    if not args.dry_run and run_output(["git", "status", "--porcelain"]):
        warning("❌ Working tree is dirty. Commit or stash before running. 🧺")
        return 1

    info("📡 Fetching remotes...")
    run(["git", "fetch", "--all", "--quiet"])

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
    failed: list[str] = []

    # One `git worktree list` for the whole run, not one per branch as the
    # shell's per-branch `worktree_for_branch` did.
    pinned_by_branch = worktree_branch_map()
    here = Path.cwd().resolve()

    for branch in branches:
        # A branch checked out in another worktree cannot be checked out here —
        # git refuses with "already used by worktree". That's a mechanical
        # limit, not a conflict, so update it in place rather than counting it
        # as a failure.
        pinned = pinned_by_branch.get(branch, "")

        if pinned and Path(pinned).resolve() != here:
            if not worktree_is_clean(pinned):
                warning(f"  ⏭️  {branch} — worktree is dirty ({pinned}), skipping")
                failed.append(branch)
                continue

            log(f"⬇️  Rebasing {branch} in its worktree ({pinned})")
            rebase = run(["git", "-C", pinned, "pull", "--rebase", "--quiet"], check=False)
            if rebase.returncode == 0:
                success(f"  ✅ {branch} up to date (in {pinned})")
                succeeded.append(branch)
            else:
                warning("  ❌ rebase failed — aborting and moving on")
                run(["git", "-C", pinned, "rebase", "--abort"], check=False, capture=True)
                failed.append(branch)
            continue

        info(f"📂 Switching to 🌿 {branch}")
        checkout = run(["git", "checkout", "--quiet", branch], check=False, capture=True)
        if checkout.returncode != 0:
            warning("  ✗ checkout failed, skipping")
            failed.append(branch)
            continue

        log(f"⬇️  Rebasing {branch} onto upstream")
        pull = run(["git", "pull", "--rebase", "--quiet"], check=False)
        if pull.returncode == 0:
            success(f"  ✅ {branch} up to date")
            succeeded.append(branch)
        else:
            warning("  ❌ rebase failed — aborting and moving on")
            run(["git", "rebase", "--abort"], check=False, capture=True)
            failed.append(branch)

    info(f"🔁 Returning to 🌿 {original_branch}")
    run(["git", "checkout", "--quiet", original_branch])

    print()
    success("═══ summary ═══")
    success(f"✅ Updated: {len(succeeded)}")
    if failed:
        warning(f"❌ Failed:  {len(failed)}")
        for branch in failed:
            warning(f"  • 💥 {branch}")
        return 1

    success("🎉 All clean!")
    return 0


if __name__ == "__main__":
    run_cli(main)
