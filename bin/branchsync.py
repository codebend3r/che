"""Branch/worktree synchronization for sync-all-branches.

Sync rebases every branch onto its upstream inside its own checkout, locked or
not, the way `git pull --rebase` does, and keeps every local change. A branch
proven merged into a main or dev branch (by content, or by GitHub's merged PR)
is deleted with its worktree; any uncommitted work there is stashed first. A
branch is only moved past its own commits (reset to an upstream that already
holds them) when a content check proves its changes are already upstream.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from pathlib import Path

from gitutils import (
    Worktree,
    abort_operation,
    git_path,
    has_changes,
    in_progress,
    local_branches,
    stash_everything,
    worktrees,
)
from report import (
    ADDED,
    FAIL,
    NOTE,
    OK,
    PLAN,
    SAME,
    WARN,
    Listing,
    Tally,
    duration,
    plural,
)
from report import Outcome as BaseOutcome
from utils import run, run_output

# A branch is "merged" when it reached one of these on origin. They are also
# never pruned themselves, whatever state their upstream is in.
BASE_BRANCHES = ("main", "master", "dev", "develop")
PROTECTED_BRANCHES = (*BASE_BRANCHES, "staging")

_PROBE_IDENTITY = {
    "GIT_AUTHOR_NAME": "che",
    "GIT_AUTHOR_EMAIL": "che@localhost",
    "GIT_COMMITTER_NAME": "che",
    "GIT_COMMITTER_EMAIL": "che@localhost",
}

TEMPORARY_PREFIX = "che-sync-"


def operation_branch(path: Path) -> str:
    """A rebase/bisect detaches HEAD but still reserves its original branch."""
    for name in ("rebase-merge/head-name", "rebase-apply/head-name", "BISECT_START"):
        file = git_path(path, name)
        if file.is_file():
            return file.read_text().splitlines()[0].removeprefix("refs/heads/")
    return ""


def short(ref: str) -> str:
    """``origin/feature`` for ``refs/remotes/origin/feature``."""
    return ref.removeprefix("refs/remotes/").removeprefix("refs/heads/")


def conflicts(output: str, shown: int = 3) -> str:
    """`` (conflict in a.py, b.py +2 more)`` from a failed rebase's output, or ""."""
    marker = "Merge conflict in "
    files = [
        line.split(marker, 1)[1].strip()
        for line in output.splitlines()
        if line.startswith("CONFLICT") and marker in line
    ]
    if not files:
        return ""
    more = f" +{len(files) - shown} more" if len(files) > shown else ""
    return f" (conflict in {', '.join(files[:shown])}{more})"


def failure(exc: subprocess.CalledProcessError | OSError) -> str:
    """A failed command as one line, with git's own last word when captured."""
    stderr = (exc.stderr or "") if isinstance(exc, subprocess.CalledProcessError) else ""
    last = next((line.strip() for line in reversed(stderr.splitlines()) if line.strip()), "")
    return f"{exc}: {last}" if last else str(exc)


class Outcome(BaseOutcome):
    """Everything a sync can conclude about a branch, defined once.

    Each member is its live line (tone and verb; no verb means the branch is
    counted silently) and its summary row (label and listing). The summary
    walks this enum in declaration order: what changed, what a dry run would
    change, what was left alone, then what needs attention, failures last.
    """

    UPDATED = (OK, "updated", "Updated", Listing.LIST)
    RESET = (OK, "reset", "Reset to upstream", Listing.LIST)
    DELETED = (OK, "deleted", "Deleted (merged)", Listing.LIST)
    TRACKED = (ADDED, "tracked", "Tracked new", Listing.LIST)
    RESTORED = (NOTE, "", "WIP restored", Listing.LIST)
    STASHED = (NOTE, "stashed", "Stashed (merged)", Listing.LIST)
    CLEARED = (NOTE, "cleared", "Cleared leftovers", Listing.LIST)
    WOULD_UPDATE = (PLAN, "would update", "Would update", Listing.LIST)
    WOULD_RESET = (PLAN, "would reset", "Would reset", Listing.LIST)
    WOULD_DELETE = (PLAN, "would delete", "Would delete", Listing.LIST)
    WOULD_TRACK = (PLAN, "would track", "Would track", Listing.LIST)
    WOULD_CLEAR = (PLAN, "would clear", "Would clear", Listing.LIST)
    CURRENT = (SAME, "", "Up to date", Listing.COUNT)
    LOCAL_ONLY = (NOTE, "", "Local only", Listing.LIST)
    DETACHED = (SAME, "skipped", "Detached, skipped", Listing.LIST)
    PROTECTED = (WARN, "protected", "Protected, gone", Listing.LIST)
    GONE = (WARN, "gone", "Upstream gone", Listing.LIST)
    MERGED_KEPT = (WARN, "kept", "Merged, kept", Listing.LIST)
    BLOCKED = (FAIL, "blocked", "Blocked", Listing.ALL)


@dataclass
class BranchSync:
    root: Path
    dry_run: bool
    tally: Tally[Outcome] = field(default_factory=lambda: Tally(Outcome))
    total: int = 0
    trees: list[Worktree] = field(init=False)

    def __post_init__(self) -> None:
        self.trees = worktrees(self.root)

    # -- git plumbing --------------------------------------------------------

    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        """``git *args`` in ``cwd`` (the repo root by default), captured and unchecked."""
        return run(["git", *args], cwd=cwd or self.root, check=False, capture=True)

    def succeeds(self, *args: str, cwd: Path | None = None) -> bool:
        return self.git(*args, cwd=cwd).returncode == 0

    def output(self, *args: str, check: bool = True) -> str:
        return run_output(["git", *args], cwd=self.root, check=check)

    def rev(self, ref: str) -> str:
        return self.output("rev-parse", "--verify", ref)

    def has_ref(self, ref: str) -> bool:
        return self.succeeds("show-ref", "--verify", "--quiet", ref)

    def is_ancestor(self, older: str, newer: str) -> bool:
        """Strict: a missing commit raises rather than reading as "not merged"."""
        result = self.git("merge-base", "--is-ancestor", older, newer)
        if result.returncode not in (0, 1):
            raise subprocess.CalledProcessError(
                result.returncode, result.args, stderr=result.stderr
            )
        return result.returncode == 0

    def includes(self, branch: str, upstream: str) -> bool:
        return self.is_ancestor(upstream, f"refs/heads/{branch}")

    def adds_nothing(self, ref: str, target: str) -> bool:
        """True when merging ``ref`` into ``target`` would leave its tree unchanged.

        Decided by content, not ancestry: a squash-merged branch, or a stale copy
        of an upstream that was rebased and force-pushed elsewhere, shares no
        commits with ``target`` even though every change it carries is already
        there. A conflict, unrelated histories, or a git older than 2.38 (no
        ``--write-tree``) all answer False, so doubt never discards anything.
        """
        merged = self.git("merge-tree", "--write-tree", target, ref)
        if merged.returncode or not merged.stdout:
            return False
        return merged.stdout.splitlines()[0] == self.output("rev-parse", f"{target}^{{tree}}")

    # Origin's refs are read once: the run fetched before it started (or, dry,
    # never fetches), and it never pushes, so they cannot move underneath it.

    @cached_property
    def bases(self) -> list[str]:
        return [ref for name in BASE_BRANCHES if self.has_ref(ref := f"refs/remotes/origin/{name}")]

    @cached_property
    def base_tips(self) -> set[str]:
        return {self.rev(base) for base in self.bases}

    @cached_property
    def can_ask_github(self) -> bool:
        # The patch-ID proofs work from cached refs; this one is a network call.
        if self.dry_run or shutil.which("gh") is None:
            return False
        return "github.com" in self.output("remote", "get-url", "origin", check=False)

    # -- reporting -----------------------------------------------------------

    def block(self, branch: str, reason: str) -> None:
        self.tally.flag(Outcome.BLOCKED, branch, reason)

    def summary(self, elapsed: float) -> None:
        """The closing table, one row per outcome in :class:`Outcome` order."""
        notes = []
        if self.tally.results[Outcome.DELETED]:
            notes.append("Restore a deleted branch with: git branch <name> <sha>")
        if self.tally.results[Outcome.GONE]:
            notes.append("Upstream gone: review them; clean-stale-branches removes them once sure.")
        notes.append(
            "Nothing pushed. Your checkout, unmerged branches and local changes are preserved."
        )
        self.tally.summary(
            "Preview" if self.dry_run else "Summary",
            facts=[plural(self.total, "branch", "branches"), duration(elapsed)],
            notes=notes,
        )

    # -- worktrees -----------------------------------------------------------

    def occupied(self) -> dict[str, Worktree]:
        """Every branch a worktree holds, mid-operation ones included."""
        result: dict[str, Worktree] = {}
        for tree in self.trees:
            path = Path(tree.path)
            branch = tree.branch
            if not branch and path.is_dir():
                branch = operation_branch(path)
            if branch:
                result[branch] = tree
            else:
                self.tally.record(Outcome.DETACHED, str(path), "detached HEAD; nothing to update")
        return result

    def pathspecs(self, path: Path) -> list[str]:
        """Never stash another registered checkout nested inside this one.

        Restrict status and stash by the same literal pathspecs, so untracked
        siblings still count as WIP while a nested worktree stays untouched.
        """
        specs = ["."]
        for tree in self.trees:
            nested = Path(tree.path)
            if nested != path and nested.is_relative_to(path):
                specs.append(f":(exclude,literal){nested.relative_to(path).as_posix()}")
        return specs

    def checked_out_here(self, tree: Worktree) -> bool:
        path = Path(tree.path).resolve()
        return path in (self.root.resolve(), Path(self.trees[0].path).resolve())

    def save_wip(self, branch: str, path: Path) -> str:
        pathspecs = self.pathspecs(path)
        if not has_changes(path, pathspecs):
            return ""
        # A superproject stash cannot preserve dirty submodule working copies.
        submodules = self.git(
            "submodule", "foreach", "--quiet", "--recursive", "git status --porcelain", cwd=path
        )
        if submodules.returncode or submodules.stdout:
            raise OSError(f"dirty/unreadable submodule in {path}; left untouched")
        return stash_everything(path, f"che sync-all-branches: {branch}", pathspecs)

    def restore_wip(self, branch: str, path: Path, oid: str) -> bool:
        if not oid:
            return True
        # Worktrees share refs/stash. Never pop the latest entry or drop a
        # recovery copy until both working-copy and index restoration succeed.
        if not self.succeeds("stash", "apply", "--index", oid, cwd=path):
            self.block(
                branch, f"WIP restoration conflicted in {path}; recovery stash retained: {oid}"
            )
            return False
        entries = run_output(["git", "stash", "list", "--format=%gd%x01%H"], cwd=path)
        matching = next(
            (
                ref
                for ref, sha in (line.split("\x01") for line in entries.splitlines())
                if sha == oid
            ),
            "",
        )
        if (
            not matching
            or run(["git", "stash", "drop", "--quiet", matching], cwd=path, check=False).returncode
        ):
            self.block(branch, f"WIP restored in {path}, but recovery stash not dropped: {oid}")
            return False
        self.tally.record(Outcome.RESTORED, branch)
        return True

    # -- updating a branch ---------------------------------------------------

    def drift(self, branch: str, upstream: str) -> str:
        """``3 new commits, 2 local replayed``: what an update brings in.

        The upstream is named only when it is not the usual ``origin/<branch>``,
        so the common line does not print the branch name twice.
        """
        source = "" if short(upstream) == f"origin/{branch}" else f" from {short(upstream)}"
        counts = self.output(
            "rev-list", "--left-right", "--count", f"{upstream}...refs/heads/{branch}", check=False
        ).split()
        if len(counts) != 2:
            return source.strip()
        incoming, outgoing = (int(count) for count in counts)
        detail = f"{incoming} new commit{'' if incoming == 1 else 's'}{source}"
        return f"{detail}, {outgoing} local replayed" if outgoing else detail

    def sync_branch(self, branch: str, upstream: str, path: Path | None) -> None:
        if path is not None:
            if not path.is_dir():
                self.block(branch, f"worktree unavailable: {path}")
                return
            if in_progress(path):
                self.block(branch, f"operation in progress in {path}; left untouched")
                return
        if self.includes(branch, upstream):
            self.tally.record(Outcome.CURRENT, branch)
            return
        # Replaying commits whose content the upstream already holds conflicts
        # for nothing: the usual cause is a parent branch squash-merged into main
        # and this branch rebased and force-pushed from another machine. When a
        # diverged branch adds nothing to its upstream, moving it there discards
        # no change. A branch merely behind fast-forwards through the rebase.
        local = f"refs/heads/{branch}"
        stale = not self.is_ancestor(local, upstream) and self.adds_nothing(local, upstream)
        if self.dry_run:
            if stale:
                self.tally.record(
                    Outcome.WOULD_RESET, branch, f"to {short(upstream)}; its changes are there"
                )
            else:
                self.tally.record(Outcome.WOULD_UPDATE, branch, self.drift(branch, upstream))
            return
        # Measured before anything moves.
        outcome, detail = (
            (Outcome.RESET, f"to {short(upstream)}; its changes were there")
            if stale
            else (Outcome.UPDATED, self.drift(branch, upstream))
        )
        # Messages name an existing worktree; a disposable checkout means nothing
        # to the reader, and one kept after a failure is reported on its own.
        where = f" in {path}" if path is not None else ""

        temporary: Path | None = None
        oid = ""
        try:
            if path is None:
                temporary = Path(tempfile.mkdtemp(prefix=TEMPORARY_PREFIX))
                path = temporary / "checkout"
                run(
                    ["git", "worktree", "add", "--quiet", str(path), branch],
                    cwd=self.root,
                    capture=True,
                )
            oid = self.save_wip(branch, path)
            if stale:
                moved = self.reset_to(branch, upstream, path, where=where)
            else:
                moved = self.rebase_onto(branch, upstream, path, where=where, oid=oid)
            restored = self.restore_wip(branch, path, oid)
            if moved and restored:
                if self.includes(branch, upstream):
                    self.tally.record(outcome, branch, detail)
                else:
                    self.block(branch, "verification failed: fetched upstream not included")
        except (subprocess.CalledProcessError, OSError) as exc:
            self.block(
                branch,
                f"{failure(exc)}{where}; recovery stash: {oid or 'see git stash list'}",
            )
        except KeyboardInterrupt:
            self.block(
                branch,
                f"interrupted; inspect {path} before resuming;"
                f" recovery stash: {oid or 'see git stash list'}",
            )
            raise
        finally:
            if temporary is not None:
                self.discard_temporary(branch, temporary)

    def reset_to(self, branch: str, upstream: str, path: Path, *, where: str) -> bool:
        # --keep, not --hard: WIP is already stashed, and --keep refuses rather
        # than overwrite anything that slipped past the stash. Not captured, so
        # git's own refusal reaches the terminal.
        if run(["git", "reset", "--quiet", "--keep", upstream], cwd=path, check=False).returncode:
            self.block(branch, f"reset failed{where}; original commits retained")
            return False
        return True

    def rebase_onto(self, branch: str, upstream: str, path: Path, *, where: str, oid: str) -> bool:
        # DELIBERATE DIVERGENCE: one fetched snapshot instead of pull's
        # per-branch fetch. Disable autostash/updateRefs so Git cannot
        # compete with our exact WIP recovery or move unrelated branches.
        # --fork-point is what `git pull --rebase` does and what a bare
        # `git rebase <upstream>` does not: it reads the upstream's reflog
        # to find where this branch left it, so after a force-push from
        # another machine only the commits made here are replayed, not the
        # dozens the upstream rewrote (which conflict for nothing).
        # Captured: git's own "Successfully rebased" chatter would break the
        # report's columns. A conflict is summarised from it instead.
        rebase = self.git(
            "-c",
            "rebase.autoStash=false",
            "-c",
            "rebase.updateRefs=false",
            "rebase",
            "--no-autostash",
            "--fork-point",
            upstream,
            cwd=path,
        )
        if rebase.returncode == 0:
            return True
        # Abort only the rebase we started. Failure to abort is fatal: applying
        # WIP or continuing is no longer safe.
        if in_progress(path) and not self.succeeds("rebase", "--abort", cwd=path):
            self.block(
                branch, f"cannot abort the rebase in {path}; recovery stash: {oid or 'none'}"
            )
            raise SystemExit(1)
        self.block(
            branch,
            f"rebase failed{where}{conflicts(rebase.stdout + rebase.stderr)};"
            " original commits retained",
        )
        return False

    def discard_temporary(self, branch: str, temporary: Path) -> None:
        # Never TemporaryDirectory: its automatic recursive deletion would erase
        # files if a hook or recovery left a dirty tree. Only git removes the
        # checkout, without force, and only when no operation is in progress.
        checkout = temporary / "checkout"
        if checkout.exists() and (
            in_progress(checkout) or not self.succeeds("worktree", "remove", str(checkout))
        ):
            self.block(branch, f"temporary worktree retained for inspection: {checkout}")
            return
        temporary.rmdir()

    # -- merged branches -----------------------------------------------------

    def merged_reason(self, branch: str, ref: str = "", *, github: bool = True) -> str:
        """How ``branch`` (or ``ref``, its tip) reached a main or dev branch on origin.

        "" when unproven.

        Four proofs, cheapest first: the tip is contained in the base; merging it
        would leave the base's tree unchanged (``adds_nothing``, a squash merge
        or a stale copy of rebased work); a one-commit probe of the branch's net
        change is already in the base by patch ID (a squash merge whose lines
        the base has since changed again, which ``adds_nothing`` sees as a
        conflict); or GitHub reports a merged PR whose head is the tip, with no
        local commit newer than the merge (covers stacked PRs rebased and
        force-pushed before a squash).
        """
        tip = self.rev(ref or f"refs/heads/{branch}")
        for base in self.bases:
            label = short(base)
            if self.succeeds("merge-base", "--is-ancestor", tip, base):
                return f"contained in {label}"
            if self.adds_nothing(tip, base):
                return f"its content is already in {label}"
            fork = self.output("merge-base", base, tip, check=False)
            if not fork:
                continue
            probe = self.output(
                "commit-tree", f"{tip}^{{tree}}", "-p", fork, "-m", "che squash probe", check=False
            )
            if probe and self.output("cherry", base, probe, check=False).startswith("-"):
                return f"squash-merged into {label}"
        return self.merged_pull_request(branch, tip) if github else ""

    def merged_pull_request(self, branch: str, tip: str) -> str:
        if not self.can_ask_github:
            return ""
        listing = run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "merged",
                "--head",
                branch,
                "--json",
                "number,headRefOid,mergedAt",
            ],
            cwd=self.root,
            check=False,
            capture=True,
        )
        if listing.returncode:
            return ""
        try:
            pulls = json.loads(listing.stdout or "[]")
        except json.JSONDecodeError:
            return ""
        tip_time = int(self.output("log", "-1", "--format=%ct", tip))
        for pull in pulls:
            # Lenient: a PR head GitHub has since garbage-collected is simply
            # not an ancestor, and the merge time still decides.
            contains = self.succeeds("merge-base", "--is-ancestor", tip, pull["headRefOid"])
            merged_at = datetime.fromisoformat(pull["mergedAt"]).timestamp()
            if contains or tip_time <= merged_at:
                return f"PR #{pull['number']} merged"
        return ""

    def merged_without_upstream(self, branch: str) -> str:
        """Why a branch with no upstream counts as merged, or "".

        GitHub deletes the remote branch on merge, so a branch pushed without
        tracking has neither an upstream nor an ``origin/<branch>`` left to
        follow. The same proofs apply, with one more guard: with no upstream to
        vouch for it, a branch holding no commit of its own (a new branch cut
        from a main that has since moved, which every ancestry or content proof
        sees as "merged") counts only when GitHub reports a merged PR for it.
        """
        ref = f"refs/heads/{branch}"
        if self.output("rev-list", "--count", ref, "--not", *self.bases) == "0":
            return self.merged_pull_request(branch, self.rev(ref))
        return self.merged_reason(branch)

    def proven_merged(self, branch: str, upstream: str, *, gone: bool) -> str:
        """Why ``branch`` counts as merged into a main or dev branch, or "".

        With its upstream still on origin, the upstream must be merged too, so
        commits pushed from elsewhere are never dropped. A branch sitting on a
        base's tip has nothing to merge yet; that is a new branch, not a merged one.
        An empty ``upstream`` is a branch that was never tracked.
        """
        if branch in PROTECTED_BRANCHES:
            return ""
        if gone:
            return self.merged_reason(branch)
        if self.rev(f"refs/heads/{branch}") in self.base_tips:
            return ""
        if not upstream:
            return self.merged_without_upstream(branch)
        reason = self.merged_reason(branch)
        if not reason or self.includes(branch, upstream):
            return reason
        return reason if self.merged_reason(branch, upstream) else ""

    def drop_merged(self, branch: str, reason: str, tree: Worktree | None) -> None:
        """Delete merged ``branch`` and ``tree``, its worktree, keeping any uncommitted work.

        DELIBERATE DIVERGENCE: only a merged branch whose upstream was gone used
        to be deleted, and its worktree was kept when dirty or mid-operation.
        Now any branch proven merged into a main or dev branch goes, upstream or
        not. Its worktree goes with it: a lock is dropped, an operation in
        progress is aborted (which leaves the branch where it was) and
        uncommitted work is stashed, so `git stash list` keeps it. Only the
        caller's own checkout, which cannot be removed from under it, stays.
        """
        tip = self.output("rev-parse", "--short", f"refs/heads/{branch}")
        if tree is not None and self.checked_out_here(tree):
            self.tally.record(
                Outcome.MERGED_KEPT, branch, f"merged ({reason}) but checked out here"
            )
            return
        if self.dry_run:
            where = f"; and its worktree {tree.path}" if tree is not None else ""
            self.tally.record(Outcome.WOULD_DELETE, branch, f"merged ({reason}) at {tip}{where}")
            return
        if tree is not None and not self.remove_worktree(branch, reason, tree):
            return
        if not self.succeeds("branch", "-D", branch):
            self.block(branch, f"merged ({reason}) but branch deletion failed")
            return
        self.tally.record(
            Outcome.DELETED,
            branch,
            f"merged ({reason}); restore: git branch {branch} {tip}",
            item=f"{branch} ({tip})",
        )

    def remove_worktree(self, branch: str, reason: str, tree: Worktree) -> bool:
        """Unlock, abort, stash and remove merged ``branch``'s worktree; True when gone."""
        worktree = Path(tree.path)
        if tree.locked:
            self.git("worktree", "unlock", tree.path)
        if worktree.is_dir():
            if in_progress(worktree) and not abort_operation(worktree):
                self.block(
                    branch, f"merged ({reason}) but cannot abort the operation in {worktree}"
                )
                return False
            try:
                # Nested registered worktrees are excluded, as in save_wip:
                # a parent's stash must never sweep up another checkout.
                stash = stash_everything(
                    worktree,
                    f"che sync-all-branches: {branch} (merged)",
                    self.pathspecs(worktree),
                )
            except (subprocess.CalledProcessError, OSError) as exc:
                self.block(branch, f"merged ({reason}) but {exc}")
                return False
            if stash:
                self.tally.record(
                    Outcome.STASHED,
                    branch,
                    f"uncommitted work saved as stash {stash}",
                    item=f"{branch}: {stash}",
                )
        if not self.succeeds("worktree", "remove", "--force", tree.path):
            self.block(branch, f"merged ({reason}) but worktree removal refused: {tree.path}")
            return False
        return True

    # -- the run -------------------------------------------------------------

    def clear_leftovers(self) -> None:
        """Remove disposable worktrees an interrupted earlier sync left behind.

        A sync killed mid-rebase leaves its temporary checkout holding the
        branch, so every later run reports that branch blocked. Aborting the
        rebase puts the branch back where it was; the checkout itself was never
        the user's workspace.
        """
        leftovers = [
            Path(tree.path)
            for tree in self.trees[1:]
            if Path(tree.path).name == "checkout"
            and Path(tree.path).parent.name.startswith(TEMPORARY_PREFIX)
        ]
        for path in leftovers:
            if self.dry_run:
                self.tally.record(
                    Outcome.WOULD_CLEAR, str(path), "leftover from an interrupted sync"
                )
                continue
            self.tally.record(Outcome.CLEARED, str(path), "leftover from an interrupted sync")
            if path.is_dir() and in_progress(path) and not abort_operation(path):
                self.block(path.name, f"cannot abort the operation in leftover {path}")
                continue
            if not self.succeeds("worktree", "remove", "--force", str(path)):
                self.block(str(path), "leftover sync checkout could not be removed")
                continue
            if path.parent.is_dir() and not any(path.parent.iterdir()):
                path.parent.rmdir()
        if leftovers and not self.dry_run:
            self.trees = worktrees(self.root)

    def update(self) -> None:
        self.clear_leftovers()
        occupied = self.occupied()
        branches = local_branches("upstream", cwd=self.root)
        self.total = len(branches)
        with self.tally.progress(self.total) as progress:
            for branch, upstream in branches:
                progress.step(branch)
                self.update_one(branch, upstream, occupied.get(branch))

    def update_one(self, branch: str, upstream: str, tree: Worktree | None) -> None:
        if not upstream and self.has_ref(f"refs/remotes/origin/{branch}"):
            upstream = f"refs/remotes/origin/{branch}"
        try:
            gone = bool(upstream) and not self.has_ref(upstream)
            if reason := self.proven_merged(branch, upstream, gone=gone):
                self.drop_merged(branch, reason, tree)
            elif not upstream:
                # Counted, not printed: a branch that was never pushed is normal,
                # and a line per branch would bury the ones that changed.
                self.tally.record(Outcome.LOCAL_ONLY, branch)
            elif gone and branch in PROTECTED_BRANCHES:
                self.tally.record(
                    Outcome.PROTECTED, branch, f"{short(upstream)} deleted; never pruned"
                )
            elif gone:
                # Usually a merged PR whose remote branch was deleted, or one
                # closed unmerged. Nothing is left to pull, so it is not a
                # failure; keep it for the user to review.
                self.tally.record(
                    Outcome.GONE, branch, f"{short(upstream)} deleted; not proven merged"
                )
            else:
                self.sync_branch(branch, upstream, Path(tree.path) if tree is not None else None)
        except (subprocess.CalledProcessError, OSError) as exc:
            self.block(branch, f"preflight failed: {failure(exc)}")
