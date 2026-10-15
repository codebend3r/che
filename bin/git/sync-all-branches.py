#!/usr/bin/env python3
"""🔄 Sync every branch: delete merged ones, rebase the rest, check out new ones.

Steps, in order:
  1. Switch the main clone to the main branch
  2. Fetch + prune every remote, once for the whole run
  3. clean-stale-branches   (delete branches whose upstream is gone)
  4. update-local-branches  (rebase every branch onto its upstream)
  5. checkout-my-branches   (track your remote branches that aren't local)

Only branches change. It never pushes, never adds, removes or prunes a
worktree, and never runs a repo's git hooks: pushing and worktrees are the
user's call, and a lefthook or husky pre-commit or pre-push gates the user's
own work, not this bookkeeping. A branch checked out in a linked worktree is
rebased in place there; a stale one is reported, not deleted. The main clone
ends on main: new branches are created without being checked out.

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

from gitutils import fetch_remotes, park_main_worktree, skip_git_hooks
from utils import (
    add_bool_flag,
    build_parser,
    env_bool,
    heading,
    info,
    log,
    require_binary,
    run,
    run_cli,
)

__version__ = "2.1.0"

SCRIPT_DIR = Path(__file__).resolve().parent


def delegate(script: str, args: list[str], *, cwd: Path) -> None:
    """Run a sibling script in the main worktree, aborting the sync if it fails.

    The shell version invoked these under ``set -e``, so a non-zero exit from
    any of them ended the run. ``check=True`` reproduces that: a branch that
    could not be rebased is a reason to stop and look, not to sail on.

    The blank line before each one is flushed: a child writes straight to the
    shared stdout, so an unflushed separator would surface after its output
    whenever the sync is piped.
    """
    print(flush=True)
    run([sys.executable, str(SCRIPT_DIR / script), *args], cwd=cwd)


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

    heading("🔄  sync-all-branches", dry_run=args.dry_run)

    # Every later step runs from the main worktree, because the delegated
    # scripts expect the main clone. Passing cwd= to each call rather than
    # `cd`-ing keeps the process's own directory untouched.
    main_wt = park_main_worktree("sync", dry_run=args.dry_run)

    # The one fetch of the run. Each delegated script fetches when run on its
    # own; here they inherit the marker fetch_remotes leaves and skip theirs.
    fetch_remotes()

    # Dry-run travels as an explicit --dry-run=true|false, never as DRY_RUN in
    # the environment, so a child can never disagree with the parent about
    # which mode this is - whatever DRY_RUN it inherited.
    mode = [f"--dry-run={'true' if args.dry_run else 'false'}"]
    delegate("clean-stale-branches.py", mode, cwd=main_wt)
    delegate("update-local-branches.py", mode, cwd=main_wt)

    checkout_args = []
    if args.author:
        checkout_args.append(f"--author={args.author}")
    if args.limit:
        checkout_args.append(f"--limit={args.limit}")

    if args.dry_run:
        print(flush=True)
        info(f"🌵 Would run: checkout-my-branches {' '.join(checkout_args)}".rstrip())
    else:
        delegate("checkout-my-branches.py", checkout_args, cwd=main_wt)

    log("🎉 Sync complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
