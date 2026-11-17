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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitutils import (
    Worktree,
    abort_operation,
    in_progress,
    skip_git_hooks,
    stash_everything,
    worktree_is_clean,
    worktrees,
)
from report import FAIL, OK, PLAN, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    dry_run_complete,
    env_bool,
    heading,
    info,
    log,
    require_binary,
    run,
    run_cli,
    run_output,
    warning,
)

__version__ = "3.0.0"


class Prune(Outcome):
    """Everything a prune can conclude about a linked worktree, in summary order."""

    STASHED = (OK, "removed", "Removed, work stashed", Listing.ALL)
    REMOVED = (OK, "removed", "Removed")
    WOULD_REMOVE = (PLAN, "would remove", "Would remove")
    KEPT = (FAIL, "failed", "Could not remove", Listing.ALL)


def preview(tally: Tally[Prune], worktree: Worktree, force: bool) -> None:
    """Record what removing ``worktree`` would take, changing nothing."""
    path = Path(worktree.path)
    notes = [
        note
        for note, applies in (
            ("locked; would unlock", worktree.locked),
            ("operation in progress; would abort", path.is_dir() and in_progress(path)),
            (
                "uncommitted changes; would discard"
                if force
                else "uncommitted changes; would stash",
                path.is_dir() and not worktree_is_clean(path),
            ),
        )
        if applies
    ]
    tally.record(Prune.WOULD_REMOVE, worktree.path, ", ".join(notes))


def remove(tally: Tally[Prune], worktree: Worktree, main_wt: Path, force: bool) -> None:
    """Remove ``worktree``, unlocking, aborting and stashing first as needed."""
    path = Path(worktree.path)

    def keep(reason: str) -> None:
        tally.record(Prune.KEPT, str(path), reason, item=f"{path}: {reason}")

    done: list[str] = []
    if worktree.locked:
        run(["git", "worktree", "unlock", str(path)], cwd=main_wt, check=False)
        done.append("unlocked")
    stash = ""
    # DELIBERATE DIVERGENCE: a dirty or mid-operation worktree used to be
    # kept unless --force was given. Every linked worktree goes now; the
    # operation is aborted and the work is stashed so nothing is lost.
    if path.is_dir():
        if in_progress(path):
            if not abort_operation(path):
                keep("could not abort the operation in progress")
                return
            done.append("aborted the operation in progress")
        if not force:
            try:
                stash = stash_everything(
                    path, f"che prune-worktrees: {worktree.branch or path.name} ({path})"
                )
            except OSError as exc:
                keep(str(exc))
                return
    removal = run(
        ["git", "worktree", "remove", "--force", str(path)],
        cwd=main_wt,
        check=False,
        capture=True,
    )
    if removal.returncode:
        keep((removal.stderr or "").strip() or "git worktree remove failed")
    elif stash:
        done.append(f"stashed {stash[:7]}")
        tally.record(Prune.STASHED, str(path), ", ".join(done), item=f"{path}: {stash}")
    else:
        tally.record(Prune.REMOVED, str(path), ", ".join(done))


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
    started = time.monotonic()

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

    tally = Tally(Prune)
    with tally.progress(len(linked)) as progress:
        for worktree in linked:
            progress.step(worktree.path)
            if args.dry_run:
                preview(tally, worktree, args.force)
            else:
                remove(tally, worktree, main_wt, args.force)

    # Captured so its lines land under the table instead of between events.
    prune = ["git", "worktree", "prune", "--verbose", *(["--dry-run"] if args.dry_run else [])]
    pruned = run(prune, cwd=main_wt, check=not args.dry_run, capture=True)
    records = [
        line.strip()
        for line in f"{pruned.stdout or ''}\n{pruned.stderr or ''}".splitlines()
        if line.strip()
    ]

    notes = [*records]
    if not args.dry_run and not records:
        notes.append("No stale worktree records to prune.")
    if tally.count(Prune.STASHED):
        notes.append("Stashed work is kept in git stash list.")
    notes.append("The main worktree is never touched.")
    tally.summary(
        "Preview" if args.dry_run else "Summary",
        facts=[plural(len(linked), "linked worktree"), duration(time.monotonic() - started)],
        notes=notes,
    )
    print()
    if count := tally.count(Prune.KEPT):
        warning(f"⚠️  {plural(count, 'worktree')} could not be removed. Every other one still was.")
        return 1
    if args.dry_run:
        dry_run_complete("removed")
    else:
        log("🎉 Prune complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
