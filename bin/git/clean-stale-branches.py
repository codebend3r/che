#!/usr/bin/env python3
"""🧹 Delete local branches whose upstream is gone (the remote branch was deleted).

Protected branches and the current branch are never deleted.

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

from utils import (
    add_bool_flag,
    build_parser,
    env_bool,
    info,
    log,
    note,
    require_binary,
    run,
    run_cli,
    run_lines,
    success,
    warning,
    worktree_branch_map,
)

__version__ = "3.1.0"

DEFAULT_PROTECTED = ("main", "master", "dev", "develop", "staging")


def current_branch() -> str:
    """The checked-out branch, or "" when HEAD is detached."""
    completed = run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        check=False,
        capture=True,
    )
    return (completed.stdout or "").strip()


def stale_branches(protected: set[str], skip: str) -> list[str]:
    """Local branches whose upstream is marked ``[gone]``.

    ``[gone]`` means the remote branch was deleted, which is what a merged and
    tidied-up PR leaves behind. It does *not* mean merged - a closed-unmerged
    PR looks identical here, same as in the shell version.
    """
    # Separator is \x01, not the shell version's '|': a branch may legally be
    # named `a|b[gone]`, which made the shell version split the record wrong
    # and delete branch `a`. Control characters are illegal in ref names.
    found = []
    for line in run_lines(
        ["git", "for-each-ref", "--format=%(refname:short)%01%(upstream:track)", "refs/heads/"]
    ):
        branch, _, track = line.partition("\x01")
        if not branch:
            continue
        if branch in protected:
            continue
        if branch == skip:
            note(f"⏭️  Skipping current branch: {branch}")
            continue
        if "[gone]" in track:
            found.append(branch)
    return found


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

    protected = set(DEFAULT_PROTECTED)
    protected.update(name for name in args.protect.split(",") if name)

    header_suffix = " 🌵 (dry run)" if args.dry_run else ""
    note("═══════════════════════════════════════════")
    note(f"🧹  clean-stale-branches{header_suffix}")
    note("═══════════════════════════════════════════")

    info("📡 Fetching + pruning remotes...")
    # Not wrapped: the shell version ran this bare under `set -e`, so a fetch
    # failure exited with git's own status (128), not a flattened 1.
    run(["git", "fetch", "--all", "--prune", "--quiet"])

    info("🔍 Scanning local branches for gone upstreams...")
    stale = stale_branches(protected, current_branch())

    if not stale:
        success("✨ No stale branches. All clean! 🎉")
        return 0

    # A branch checked out in a worktree cannot be deleted — git refuses with
    # "already used by worktree". Split those out so one pinned branch doesn't
    # abort the whole run; sync-all-branches collapses worktrees before it gets
    # here, so this only bites when the script is run on its own.
    # One `git worktree list` for the whole set, not one per branch as the
    # shell's per-branch `worktree_for_branch` did.
    pinned_by_branch = worktree_branch_map()
    deletable = [branch for branch in stale if branch not in pinned_by_branch]
    pinned = [(branch, pinned_by_branch[branch]) for branch in stale if branch in pinned_by_branch]

    if pinned:
        warning(f"⏭️  {len(pinned)} stale branch(es) are checked out in a worktree:")
        for branch, path in pinned:
            warning(f"  • 🌿 {branch} (in {path})")
        info("💡 Run sync-all-branches to push and collapse those worktrees first.")

    if not deletable:
        success("✨ Nothing left to delete. 🎉")
        return 0

    if args.dry_run:
        warning(f"🌵 {len(deletable)} stale branch(es) would be deleted:")
        for branch in deletable:
            warning(f"  • 🪦 {branch}")
        log("💡 Dry run complete. Nothing was actually deleted.")
        return 0

    for branch in deletable:
        warning(f"🗑️  Deleting: {branch}")
        run(["git", "branch", "-D", branch])

    success(f"✨ Removed {len(deletable)} stale branch(es). 🎉")
    return 0


if __name__ == "__main__":
    run_cli(main)
