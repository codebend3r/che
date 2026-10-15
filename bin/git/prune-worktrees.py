#!/usr/bin/env python3
"""🌿 Remove every linked worktree in the current repository, then prune records.

The main worktree (the one containing .git) is always left untouched.

Usage:
  prune-worktrees.py [--dry-run] [--force]

Options:
  --dry-run    Show what would be removed, change nothing
  --force      Pass --force to 'git worktree remove' (drops dirty trees)
  --help       Show help

Env:
  DRY_RUN=true Same as --dry-run (used by the .zshrc -dr wrapper)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitutils import park_main_worktree, skip_git_hooks, worktrees
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

__version__ = "1.3.0"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="prune-worktrees",
        description="🌿 Remove every linked worktree, then prune stale admin records.",
    )
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", True),
        help="Show what would be removed, change nothing",
    )
    add_bool_flag(
        parser,
        "--force",
        help="Pass --force to 'git worktree remove' (drops dirty trees)",
    )
    args = parser.parse_args(argv)

    require_binary("git")
    # Parking the main worktree is a `git checkout`, which fires post-checkout.
    skip_git_hooks()

    heading("🌿  prune-worktrees", dry_run=args.dry_run)

    # Work from the main worktree: removing a worktree fails while standing
    # inside it.
    main_wt = park_main_worktree("prune", dry_run=args.dry_run)

    info("🔍 Listing worktrees...")
    linked = [worktree.path for worktree in worktrees(main_wt)[1:]]

    if not linked:
        success("✨ No linked worktrees. Running prune anyway... 🎉")
        if args.dry_run:
            run(["git", "worktree", "prune", "--dry-run", "--verbose"], check=False, cwd=main_wt)
            dry_run_complete("pruned")
        else:
            run(["git", "worktree", "prune", "--verbose"], cwd=main_wt)
            success("✨ Pruned stale worktree records. 🎉")
        return 0

    if args.dry_run:
        warning(f"🌵 {len(linked)} worktree(s) would be removed:")
        for path in linked:
            warning(f"  • 🪦 {path}")
        info("📜 Would also run: git worktree prune --verbose")
        dry_run_complete("removed")
        return 0

    remove_args = ["--force"] if args.force else []
    for path in linked:
        warning(f"🗑️  Removing: {path}")
        run(["git", "worktree", "remove", *remove_args, path], cwd=main_wt)

    info("🧹 Pruning stale worktree records...")
    run(["git", "worktree", "prune", "--verbose"], cwd=main_wt)
    success(f"✨ Removed {len(linked)} worktree(s). 🎉")
    return 0


if __name__ == "__main__":
    run_cli(main)
