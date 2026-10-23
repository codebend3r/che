#!/usr/bin/env python3
"""🌿 Remove every linked worktree in the current repository, then prune records.

The main worktree (the one containing .git) is always left untouched; every
other worktree goes, locked or not, dirty or not, mid-rebase or not. A lock is
dropped first, an operation in progress (rebase, merge, cherry-pick, revert,
bisect) is aborted, and uncommitted tracked and untracked work is stashed so
`git stash list` still has it after the directory is gone. --force removes
without stashing. One failure never stops the rest.

Usage:
  prune-worktrees.py [--dry-run] [--force]

Options:
  --dry-run    Show what would be removed, change nothing
  --force      Discard uncommitted changes instead of stashing them
  --help       Show help

Env:
  DRY_RUN=true Same as --dry-run (used by the .zshrc -dr wrapper)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitutils import (
    abort_operation,
    in_progress,
    skip_git_hooks,
    stash_everything,
    worktree_is_clean,
    worktrees,
)
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
    run_output,
    success,
    warning,
)

__version__ = "2.0.0"


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
        help="Discard uncommitted changes instead of stashing them",
    )
    args = parser.parse_args(argv)

    require_binary("git")
    # Aborting a rebase or stashing can fire the repo's hooks.
    skip_git_hooks()

    heading("🌿  prune-worktrees", dry_run=args.dry_run)

    if run_output(["git", "rev-parse", "--is-inside-work-tree"], check=False) != "true":
        warning("❌ Not inside a git working tree.")
        return 1

    # DELIBERATE DIVERGENCE: this used to park the main worktree on main first,
    # and refused outright when the main worktree had uncommitted changes.
    # Removing linked worktrees never needs the main one's branch to change,
    # so git runs from the main worktree as it is.
    main_wt = Path(worktrees()[0].path)

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
            path = Path(worktree.path)
            notes = [
                note
                for note, applies in (
                    ("locked; would unlock", worktree.locked),
                    ("operation in progress; would abort", path.is_dir() and in_progress(path)),
                    (
                        "uncommitted changes; would discard"
                        if args.force
                        else "uncommitted changes; would stash",
                        path.is_dir() and not worktree_is_clean(path),
                    ),
                )
                if applies
            ]
            suffix = f" ({', '.join(notes)})" if notes else ""
            warning(f"  • 🪦 {worktree.path}{suffix}")
        info("📜 Would also run: git worktree prune --verbose")
        dry_run_complete("removed")
        return 0

    removed = 0
    kept: list[str] = []
    stashes: list[str] = []
    for worktree in linked:
        path = Path(worktree.path)
        warning(f"🗑️  Removing: {path}")
        if worktree.locked:
            info("  🔓 Unlocking")
            run(["git", "worktree", "unlock", str(path)], cwd=main_wt, check=False)
        # DELIBERATE DIVERGENCE: a dirty or mid-operation worktree used to be
        # kept unless --force was given. Every linked worktree goes now; the
        # operation is aborted and the work is stashed so nothing is lost.
        if path.is_dir():
            if in_progress(path):
                info("  ⏹️  Aborting the operation in progress")
                if not abort_operation(path):
                    warning(f"  ❌ Could not abort the operation in {path}; kept")
                    kept.append(str(path))
                    continue
            if not args.force:
                try:
                    stash = stash_everything(
                        path, f"che prune-worktrees: {worktree.branch or path.name} ({path})"
                    )
                except OSError as exc:
                    warning(f"  ❌ {exc}; kept")
                    kept.append(str(path))
                    continue
                if stash:
                    info(f"  🧺 Stashed uncommitted work: {stash}")
                    stashes.append(f"{path}: {stash}")
        removal = run(
            ["git", "worktree", "remove", "--force", str(path)],
            cwd=main_wt,
            check=False,
        )
        if removal.returncode:
            warning(f"  ❌ Could not remove: {path}")
            kept.append(str(path))
        else:
            removed += 1

    info("🧹 Pruning stale worktree records...")
    run(["git", "worktree", "prune", "--verbose"], cwd=main_wt)
    success(f"✨ Removed {removed} worktree(s). 🎉")
    if stashes:
        info(f"🧺 {len(stashes)} worktree(s) had uncommitted work, kept in git stash list:")
        for entry in stashes:
            info(f"  • {entry}")
    if kept:
        warning(f"⚠️  {len(kept)} worktree(s) kept:")
        for path in kept:
            warning(f"  • {path}")
        return 1
    return 0


if __name__ == "__main__":
    run_cli(main)
