#!/usr/bin/env python3
"""🌿 Remove every linked worktree in the current repository, then prune records.

The main worktree (the one containing .git) is always left untouched. A locked
worktree is unlocked first, since a lock only guards against an accidental
removal and this command is the deliberate one. A worktree with uncommitted
changes is kept, lock and all, unless --force is given; one failure never stops
the rest.

Usage:
  prune-worktrees.py [--dry-run] [--force]

Options:
  --dry-run    Show what would be removed, change nothing
  --force      Remove worktrees with uncommitted changes too
  --help       Show help

Env:
  DRY_RUN=true Same as --dry-run (used by the .zshrc -dr wrapper)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitutils import park_main_worktree, skip_git_hooks, worktree_is_clean, worktrees
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

__version__ = "1.4.0"


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
        help="Remove worktrees with uncommitted changes too",
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
    linked = worktrees(main_wt)[1:]

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
        for worktree in linked:
            note = " (locked; would unlock first)" if worktree.locked else ""
            warning(f"  • 🪦 {worktree.path}{note}")
        info("📜 Would also run: git worktree prune --verbose")
        dry_run_complete("removed")
        return 0

    removed = 0
    kept: list[str] = []
    for worktree in linked:
        warning(f"🗑️  Removing: {worktree.path}")
        # DELIBERATE DIVERGENCE: a lock used to abort the whole run with git's
        # "cannot remove a locked working tree". Unlock, but only once the
        # removal is certain to be allowed, so a kept worktree keeps its lock.
        # A checkout whose directory is gone has no work left to lose.
        gone = not Path(worktree.path).is_dir()
        if not (args.force or gone) and not worktree_is_clean(worktree.path):
            warning("  ⏭️  Uncommitted changes; kept (use --force to remove)")
            kept.append(worktree.path)
            continue
        if worktree.locked:
            info("  🔓 Unlocking")
            run(["git", "worktree", "unlock", worktree.path], cwd=main_wt, check=False)
        removal = run(
            [
                "git",
                "worktree",
                "remove",
                *(["--force"] if args.force or gone else []),
                worktree.path,
            ],
            cwd=main_wt,
            check=False,
        )
        if removal.returncode:
            warning(f"  ❌ Could not remove: {worktree.path}")
            kept.append(worktree.path)
        else:
            removed += 1

    info("🧹 Pruning stale worktree records...")
    run(["git", "worktree", "prune", "--verbose"], cwd=main_wt)
    success(f"✨ Removed {removed} worktree(s). 🎉")
    if kept:
        warning(f"⚠️  {len(kept)} worktree(s) kept:")
        for path in kept:
            warning(f"  • {path}")
        return 1
    return 0


if __name__ == "__main__":
    run_cli(main)
