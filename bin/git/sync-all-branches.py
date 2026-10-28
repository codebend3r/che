#!/usr/bin/env python3
"""🔄 Update every branch and worktree, and prune what has been merged.

Fetch once, delete branches (and their worktrees) that were merged into a main
or dev branch, rebase the rest onto their upstream (or origin/<branch>) the way
`git pull --rebase` does, and track every origin feature branch that is not
local yet and not merged. Worktrees stay worktrees and are updated in place. A
branch whose changes are all already upstream moves to its upstream instead of
replaying them. Dirty tracked/untracked work is saved in an exact recovery
stash and restored with its index; a merged worktree's work stays stashed.
Conflicts are reported; independent branches continue. Nothing is pushed.

Usage:
  sync-all-branches.py [--dry-run] [--author=EMAIL] [--limit=N]

Options:
  --dry-run        Preview cached refs only; no fetch or changes
  --author=EMAIL   Only track new origin branches by this author (default: all)
  --limit=N        Recent origin refs to scan for new branches (default: 100)
  --help           Show help

Env:
  DRY_RUN=true     Same as --dry-run (used by the shell -dr wrapper)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from branchsync import BranchSync
from gitutils import current_branch, fetch_remotes, for_each_ref, local_branches, skip_git_hooks
from utils import (
    add_bool_flag,
    build_parser,
    env_bool,
    heading,
    info,
    log,
    parse_count,
    require_binary,
    run,
    run_cli,
    run_output,
    warning,
)

__version__ = "4.0.1"


def track_new(sync: BranchSync, author: str, limit: int) -> list[str]:
    tracked: list[str] = []
    # A branch just deleted as merged may have been proven only through its
    # GitHub PR, which the check below skips, so it would be tracked right back.
    local = {branch for (branch,) in local_branches(cwd=sync.root)} | set(sync.deleted)
    refs = for_each_ref(
        "refs/remotes/origin/",
        "authoremail:trim",
        "refname:lstrip=3",
        "symref",
        sort="-committerdate",
        cwd=sync.root,
    )
    for email, branch, symref in refs[:limit]:
        if symref or branch == "HEAD" or branch in local or (author and email != author):
            continue
        # DELIBERATE DIVERGENCE: only your own branches used to be tracked, and
        # merged ones came back after every prune. Every feature branch is
        # tracked now, except one already merged into a main or dev branch.
        # No GitHub lookup here: one per remote branch would be too slow.
        if sync.merged_reason(branch, f"refs/remotes/origin/{branch}", github=False):
            continue
        if sync.dry_run:
            info(f"🌵 Would track: {branch}")
            continue
        if run(
            ["git", "branch", "--track", branch, f"refs/remotes/origin/{branch}"],
            cwd=sync.root,
            check=False,
        ).returncode:
            sync.block(branch, "could not create tracking branch")
        else:
            tracked.append(branch)
    return tracked


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="sync-all-branches",
        description="🔄 Update every branch and worktree, and prune what has been merged.",
    )
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", False),
        help="Preview cached refs only; no fetch or changes",
    )
    # Compatibility with chip and older wrappers. Neither pushing nor lock
    # removal is ever part of syncing, regardless of these legacy flags.
    add_bool_flag(parser, "--no-push", allow_value=False, help=argparse.SUPPRESS)
    add_bool_flag(parser, "--keep-locked", help=argparse.SUPPRESS)
    parser.add_argument(
        "--author",
        default="",
        metavar="EMAIL",
        help="Only track new origin branches by this author (default: all)",
    )
    parser.add_argument(
        "--limit",
        default="100",
        metavar="N",
        help="Recent origin refs to scan for new branches (default: 100)",
    )
    args = parser.parse_args(argv)
    limit = parse_count(args.limit, "--limit", minimum=1)
    require_binary("git")
    skip_git_hooks()
    heading("🔄  sync-all-branches", dry_run=args.dry_run)
    if run_output(["git", "rev-parse", "--is-inside-work-tree"], check=False) != "true":
        warning("❌ Not inside a git working tree.")
        return 1
    root = Path(run_output(["git", "rev-parse", "--show-toplevel"]))
    original = current_branch(root) or run_output(["git", "rev-parse", "--short", "HEAD"], cwd=root)
    info(f"📍 Keeping caller checkout: {original}")
    # DELIBERATE DIVERGENCE: the old sync parked on main and delegated cleanup.
    # Preserve active workspaces instead, and never delete a gone-upstream
    # branch merely because its remote was deleted: only once it is proven
    # merged (BranchSync.proven_merged). Dry-run must not fetch.
    if args.dry_run:
        info("🌵 Cached remote refs only; no fetch. Results reflect the last fetch.")
    else:
        fetch_remotes()
    sync = BranchSync(root, args.dry_run)
    sync.update()
    try:
        tracked = track_new(sync, args.author, limit)
    except (subprocess.CalledProcessError, OSError) as exc:
        sync.block("new origin branches", str(exc))
        tracked = []
    sync.summary(tracked)
    if sync.blocked:
        warning(
            "Sync partially completed; blocked branches need attention. Remaining independent branches were attempted."
        )
        return 1
    log("🎉 Preview complete." if args.dry_run else "🎉 Sync complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
