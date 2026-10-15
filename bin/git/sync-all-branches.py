#!/usr/bin/env python3
"""🔄 Sync every branch: delete merged ones, rebase the rest, check out new ones.

Steps, in order:
  1. git fetch --all --prune
  2. Switch the main clone to the main branch
  3. clean-stale-branches   (delete branches whose upstream is gone)
  4. update-local-branches  (rebase every branch onto its upstream)
  5. checkout-my-branches   (check out your remote branches that aren't local)

Only branches change. It never pushes, never adds, removes or prunes a
worktree, and never runs a repo's git hooks: pushing and worktrees are the
user's call, and a lefthook or husky pre-commit or pre-push gates the user's
own work, not this bookkeeping. A branch checked out in a linked worktree is
rebased in place there; a stale one is reported, not deleted.

Usage:
  sync-all-branches.py [--dry-run] [--author=EMAIL] [--limit=N]

Options:
  --dry-run        Report what would be deleted / synced, change nothing
  --author=EMAIL   Passed through to checkout-my-branches
  --limit=N        Passed through to checkout-my-branches
  --help           Show help

Env:
  DRY_RUN=true     Same as --dry-run (used by the .zshrc -dr wrapper)
"""

from __future__ import annotations

import argparse
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
    main_worktree,
    note,
    require_binary,
    run,
    run_cli,
    run_output,
    skip_git_hooks,
    warning,
)

__version__ = "2.0.0"

SCRIPT_DIR = Path(__file__).resolve().parent


def delegate(script: str, args: list[str], *, cwd: Path, dry_run: bool) -> None:
    """Run a sibling script in the main worktree, aborting the sync if it fails.

    The shell version invoked these under ``set -e``, so a non-zero exit from
    any of them ended the run. ``check=True`` reproduces that: a branch that
    could not be rebased is a reason to stop and look, not to sail on.

    DRY_RUN is passed explicitly rather than inherited, so the child can never
    disagree with the parent about which mode this is.
    """
    run(
        [sys.executable, str(SCRIPT_DIR / script), *args],
        cwd=cwd,
        env={"DRY_RUN": "true" if dry_run else "false"},
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="sync-all-branches",
        description="🔄 Delete merged branches, rebase the rest, check out new ones.",
    )
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", False),
        help="Report what would be deleted / synced, change nothing",
    )
    # Accepted and ignored, from when the sync pushed and collapsed worktrees:
    # chip's "Update from Origin" still passes --no-push and must keep running.
    add_bool_flag(parser, "--no-push", allow_value=False, help=argparse.SUPPRESS)
    add_bool_flag(parser, "--keep-locked", help=argparse.SUPPRESS)
    parser.add_argument(
        "--author",
        default="",
        metavar="EMAIL",
        help="Passed through to checkout-my-branches",
    )
    parser.add_argument(
        "--limit",
        default="",
        metavar="N",
        help="Passed through to checkout-my-branches",
    )
    args = parser.parse_args(argv)

    require_binary("git")
    skip_git_hooks()

    inside = run(["git", "rev-parse", "--is-inside-work-tree"], check=False, capture=True)
    if inside.returncode != 0:
        warning("❌ Not inside a git working tree.")
        return 1

    header_suffix = " 🌵 (dry run)" if args.dry_run else ""
    note("═══════════════════════════════════════════")
    note(f"🔄  sync-all-branches{header_suffix}")
    note("═══════════════════════════════════════════")

    # Every later step runs from the main worktree, because the delegated
    # scripts expect the main clone. Passing cwd= to each call rather than
    # `cd`-ing keeps the process's own directory untouched.
    main_wt_raw = main_worktree()
    if not main_wt_raw:
        warning("❌ Could not determine main worktree.")
        return 1

    main_wt = Path(main_wt_raw)

    main_branch = find_main_branch(main_wt)
    if not main_branch:
        warning("❌ Neither 'main' nor 'master' exists locally — refusing to sync.")
        return 1

    # -----------------------------------------------------------------------
    # Step 1 — fetch + prune
    # -----------------------------------------------------------------------

    info("📡 Fetching + pruning remotes...")
    if args.dry_run:
        info("🌵 Would run: git fetch --all --prune")
    else:
        run(["git", "fetch", "--all", "--prune", "--quiet"], cwd=main_wt)

    # -----------------------------------------------------------------------
    # Step 2 — park on main before anything tries to delete or rebase branches
    # -----------------------------------------------------------------------

    current = run_output(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"], check=False, cwd=main_wt
    ).strip()

    if current != main_branch:
        # Only tracked changes block: untracked files (including worktrees
        # nested under the main worktree) are not touched by checkout.
        if run_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=main_wt):
            warning("❌ Main worktree has uncommitted changes — commit or stash first. 🧺")
            return 1

        if args.dry_run:
            info(f"🌵 Would switch to 🌿 {main_branch} (currently on {current or 'detached'})")
        else:
            info(f"🔀 Switching to 🌿 {main_branch} (from {current or 'detached'})")
            run(["git", "checkout", "--quiet", main_branch], cwd=main_wt)
    else:
        info(f"📍 Already on 🌿 {main_branch}")

    # -----------------------------------------------------------------------
    # Steps 3-5 — delegate to the single-purpose scripts
    # -----------------------------------------------------------------------

    delegate_args = ["--dry-run"] if args.dry_run else []

    print()
    delegate("clean-stale-branches.py", delegate_args, cwd=main_wt, dry_run=args.dry_run)

    print()
    delegate("update-local-branches.py", delegate_args, cwd=main_wt, dry_run=args.dry_run)

    checkout_args = []
    if args.author:
        checkout_args.append(f"--author={args.author}")
    if args.limit:
        checkout_args.append(f"--limit={args.limit}")

    print()
    if args.dry_run:
        info(f"🌵 Would run: checkout-my-branches {' '.join(checkout_args)}".rstrip())
    else:
        delegate("checkout-my-branches.py", checkout_args, cwd=main_wt, dry_run=args.dry_run)

    log("🎉 Sync complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
