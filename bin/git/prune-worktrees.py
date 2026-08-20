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

from utils import (
    add_bool_flag,
    build_parser,
    env_bool,
    find_main_branch,
    info,
    log,
    note,
    require_binary,
    run,
    run_cli,
    run_output,
    success,
    warning,
    worktree_paths,
)

__version__ = "1.2.0"


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

    inside = run(["git", "rev-parse", "--is-inside-work-tree"], check=False, capture=True)
    if inside.returncode != 0:
        warning("❌ Not inside a git working tree.")
        return 1

    header_suffix = " 🌵 (dry run)" if args.dry_run else ""
    note("═══════════════════════════════════════════")
    note(f"🌿  prune-worktrees{header_suffix}")
    note("═══════════════════════════════════════════")

    # Work from the main worktree: removing a worktree fails while standing
    # inside it, and starting from a known-good branch keeps this predictable.
    paths = worktree_paths()
    if not paths:
        warning("❌ Could not determine main worktree.")
        return 1

    main_wt = Path(paths[0])
    linked = [p for p in paths[1:] if Path(p) != main_wt]

    main_branch = find_main_branch(main_wt)
    if not main_branch:
        warning("❌ Neither 'main' nor 'master' exists locally — refusing to prune.")
        return 1

    current = run_output(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"], check=False, cwd=main_wt
    ).strip()

    if current != main_branch:
        # Only block on tracked-file changes: untracked files (including linked
        # worktrees nested under the main worktree) won't be touched by checkout.
        dirty = run_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=main_wt)
        if dirty:
            warning("❌ Main worktree has uncommitted changes — commit or stash before pruning. 🧺")
            return 1
        if args.dry_run:
            info(
                f"🌵 Would switch main worktree to 🌿 {main_branch} (currently on {current or 'detached'})"
            )
        else:
            info(f"🔀 Switching main worktree to 🌿 {main_branch} (from {current or 'detached'})")
            run(["git", "checkout", "--quiet", main_branch], cwd=main_wt)
    else:
        info(f"📍 Main worktree already on 🌿 {main_branch}")

    info("🔍 Listing worktrees...")

    if not linked:
        success("✨ No linked worktrees. Running prune anyway... 🎉")
        if args.dry_run:
            run(["git", "worktree", "prune", "--dry-run", "--verbose"], check=False, cwd=main_wt)
            log("💡 Dry run complete. Nothing was actually pruned.")
        else:
            run(["git", "worktree", "prune", "--verbose"], cwd=main_wt)
            success("✨ Pruned stale worktree records. 🎉")
        return 0

    if args.dry_run:
        warning(f"🌵 {len(linked)} worktree(s) would be removed:")
        for path in linked:
            warning(f"  • 🪦 {path}")
        info("📜 Would also run: git worktree prune --verbose")
        log("💡 Dry run complete. Nothing was actually removed.")
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
