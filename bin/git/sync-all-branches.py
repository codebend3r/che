#!/usr/bin/env python3
"""🔄 Sync everything: push every worktree, collapse the pushed ones, then tidy branches.

A worktree is a temporary workspace. Once its commits are on origin, the
directory holds nothing the remote does not, so it is removed and the branch
stays behind as a plain local branch that the later steps can update normally.
That also clears the "already used by worktree" pin, which is what otherwise
makes main un-checkoutable and stale branches un-deletable.

Steps, in order:
  1. git fetch --all --prune
  2. Push every linked worktree's branch to origin
  3. Remove each pushed + clean worktree, keeping its branch
  4. Prune stale worktree admin records
  5. Switch the main clone to the main branch
  6. clean-stale-branches   (delete branches whose upstream is gone)
  7. update-local-branches  (rebase every branch onto its upstream)
  8. checkout-my-branches   (check out your remote branches that aren't local)

A worktree is only collapsed when it is clean AND fully pushed. Anything else
is kept and reported with the reason.

Usage:
  sync-all-branches.py [--dry-run] [--no-push] [--keep-locked]
                       [--author=EMAIL] [--limit=N]

Options:
  --dry-run        Report what would be pushed / removed / synced, change nothing
  --no-push        Never push; only collapse worktrees that are already pushed
  --keep-locked    Leave locked worktrees alone (default: release the lock once
                   the worktree is pushed and clean)
  --author=EMAIL   Passed through to checkout-my-branches
  --limit=N        Passed through to checkout-my-branches
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
    branch_is_pushed,
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
    success,
    warning,
    worktree_branch_map,
    worktree_is_clean,
)

__version__ = "1.0.0"

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


def collapse_worktrees(
    *,
    main_wt: Path,
    push: bool,
    keep_locked: bool,
    dry_run: bool,
) -> tuple[list[str], list[str], list[str]]:
    """Push, then remove, every linked worktree that is clean and fully pushed.

    Returns ``(pushed, collapsed, kept)`` for the summary. ``kept`` entries
    carry the reason, because "nothing happened" is the one outcome a user
    needs explained.
    """
    pushed: list[str] = []
    collapsed: list[str] = []
    kept: list[str] = []

    info("🌿 Inspecting linked worktrees...")

    # Snapshot the map first: removing a worktree mutates the list git reports.
    worktrees = [
        (branch, path)
        for branch, path in worktree_branch_map(cwd=main_wt).items()
        if path and Path(path) != main_wt
    ]

    if not worktrees:
        info("  ℹ️  No linked worktrees with a branch checked out.")  # noqa: RUF001

    for branch, path in worktrees:
        # A dirty worktree holds work that only exists there. Never touch it.
        if not worktree_is_clean(path):
            kept.append(f"{branch} ({path}) — dirty")
            warning(f"  ⏭️  {branch} — dirty, keeping {path}")
            continue

        # Push whatever is not on origin yet, so the directory becomes redundant.
        if not branch_is_pushed(branch, cwd=main_wt):
            if not push:
                kept.append(f"{branch} ({path}) — unpushed, --no-push")
                warning(f"  ⏭️  {branch} — unpushed and --no-push, keeping {path}")
                continue

            if dry_run:
                info(f"  🌵 Would push: {branch} → origin")
                pushed.append(branch)
            else:
                log(f"  ⬆️  Pushing {branch} → origin")
                result = run(
                    ["git", "-C", path, "push", "--quiet", "--set-upstream", "origin", branch],
                    check=False,
                )
                if result.returncode != 0:
                    kept.append(f"{branch} ({path}) — push failed")
                    warning(f"  ❌ push failed for {branch}, keeping {path}")
                    continue
                pushed.append(branch)

        # Re-check rather than assume: a push can succeed and still leave the
        # branch behind its upstream if someone else pushed in between.
        if not dry_run and not branch_is_pushed(branch, cwd=main_wt):
            kept.append(f"{branch} ({path}) — still not fully pushed")
            warning(f"  ⏭️  {branch} — still not fully pushed, keeping {path}")
            continue

        if dry_run:
            info(f"  🌵 Would collapse: {path} (branch {branch} kept)")
            collapsed.append(f"{branch} ({path})")
            continue

        # A lock is metadata stamped by whatever created the worktree (a tool,
        # an agent, the user), and `git worktree remove` refuses while one is
        # set. The lock says nothing about unsaved work — the clean and pushed
        # gates above are what protect that — so release it rather than
        # skipping. This is NOT --force, which is the flag that discards work.
        if not keep_locked:
            run(["git", "worktree", "unlock", path], check=False, capture=True, cwd=main_wt)

        removed = run(["git", "worktree", "remove", path], check=False, cwd=main_wt)
        if removed.returncode == 0:
            success(f"  ✅ Collapsed {path} — branch {branch} kept")
            collapsed.append(f"{branch} ({path})")
        else:
            kept.append(f"{branch} ({path}) — removal failed (locked?)")
            warning(f"  ❌ Could not remove {path}")

    return pushed, collapsed, kept


def report(
    *,
    pushed: list[str],
    collapsed: list[str],
    kept: list[str],
    started_in: Path,
    main_wt: Path,
) -> None:
    """Print the worktree summary."""
    print()
    note("─────────────────────────────────────────────")
    success("═══ worktree summary ═══")
    success(f"⬆️  Pushed:    {len(pushed)}")
    for branch in pushed:
        success(f"  • 🌿 {branch}")
    success(f"📦 Collapsed: {len(collapsed)}")
    for branch in collapsed:
        success(f"  • 🪦 {branch}")
    if kept:
        warning(f"⏭️  Kept:      {len(kept)}")
        for branch in kept:
            warning(f"  • 🌿 {branch}")

    if started_in != main_wt:
        info(f"📍 Started in {started_in}; finished in {main_wt}.")
        if not started_in.is_dir():
            warning(f"⚠️  {started_in} was collapsed — your shell is in a stale directory.")
            warning(f"   Run: cd {main_wt}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="sync-all-branches",
        description="🔄 Push every worktree, collapse the pushed ones, then tidy branches.",
    )
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", False),
        help="Report what would be pushed / removed / synced, change nothing",
    )
    add_bool_flag(
        parser,
        "--no-push",
        allow_value=False,
        help="Never push; only collapse worktrees that are already pushed",
    )
    add_bool_flag(
        parser,
        "--keep-locked",
        help="Leave locked worktrees alone (default: release the lock once pushed and clean)",
    )
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

    inside = run(["git", "rev-parse", "--is-inside-work-tree"], check=False, capture=True)
    if inside.returncode != 0:
        warning("❌ Not inside a git working tree.")
        return 1

    header_suffix = " 🌵 (dry run)" if args.dry_run else ""
    note("═══════════════════════════════════════════")
    note(f"🔄  sync-all-branches{header_suffix}")
    note("═══════════════════════════════════════════")

    # Every later step runs from the main worktree: a worktree cannot be
    # removed while we are standing inside it, and the delegated scripts
    # expect the main clone.
    main_wt_raw = main_worktree()
    if not main_wt_raw:
        warning("❌ Could not determine main worktree.")
        return 1

    main_wt = Path(main_wt_raw)
    # The shell version `cd`-ed here. Passing cwd= to each call instead keeps
    # the process's own directory untouched, so a caller that sourced this in
    # the same shell would not be moved out from under itself.
    started_in = Path.cwd().resolve()

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
    # Steps 2-3 — push every worktree, then collapse the pushed ones
    # -----------------------------------------------------------------------

    pushed, collapsed, kept = collapse_worktrees(
        main_wt=main_wt,
        push=not args.no_push,
        keep_locked=args.keep_locked,
        dry_run=args.dry_run,
    )

    # -----------------------------------------------------------------------
    # Step 4 — prune stale admin records
    # -----------------------------------------------------------------------

    if args.dry_run:
        info("🌵 Would run: git worktree prune")
    else:
        run(["git", "worktree", "prune"], cwd=main_wt)

    # -----------------------------------------------------------------------
    # Step 5 — park on main before anything tries to delete or rebase branches
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
    # Steps 6-8 — delegate to the single-purpose scripts
    # -----------------------------------------------------------------------

    delegate_args = ["--dry-run"] if args.dry_run else []

    # DELIBERATE DIVERGENCE: the summary is printed even when a delegate fails.
    # The pushes and collapses above already happened; aborting without saying
    # which ones would leave the user guessing what state the repo is in.
    try:
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
    except BaseException:
        report(
            pushed=pushed, collapsed=collapsed, kept=kept, started_in=started_in, main_wt=main_wt
        )
        raise

    report(pushed=pushed, collapsed=collapsed, kept=kept, started_in=started_in, main_wt=main_wt)

    log("🎉 Sync complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
