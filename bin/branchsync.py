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
from pathlib import Path

from gitutils import (
    Worktree,
    abort_operation,
    git_path,
    in_progress,
    local_branches,
    stash_everything,
    worktrees,
)
from utils import info, run, run_output, success, warning

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


@dataclass
class BranchSync:
    root: Path
    dry_run: bool
    updated: list[str] = field(default_factory=list)
    current: list[str] = field(default_factory=list)
    local_only: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    reset: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    merged_kept: list[str] = field(default_factory=list)
    stashed: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    trees: list[Worktree] = field(init=False)

    def __post_init__(self) -> None:
        self.trees = worktrees(self.root)

    def block(self, branch: str, reason: str) -> None:
        message = f"{branch}: {reason}"
        self.blocked.append(message)
        warning(f"  ❌ {message}")

    def occupied(self) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for tree in self.trees:
            path = Path(tree.path)
            branch = tree.branch
            if not branch and path.is_dir():
                branch = operation_branch(path)
            if branch:
                result[branch] = path
            else:
                info(f"  ℹ️ Detached worktree unchanged (no upstream): {path}")  # noqa: RUF001
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

    def dirty(self, path: Path) -> bool:
        return bool(
            run_output(
                [
                    "git",
                    "status",
                    "--porcelain",
                    "-z",
                    "--untracked-files=all",
                    "--",
                    *self.pathspecs(path),
                ],
                cwd=path,
            )
        )

    def has_ref(self, ref: str) -> bool:
        return (
            run(
                ["git", "show-ref", "--verify", "--quiet", ref],
                cwd=self.root,
                check=False,
                capture=True,
            ).returncode
            == 0
        )

    def includes(self, branch: str, upstream: str) -> bool:
        return self.is_ancestor(upstream, f"refs/heads/{branch}")

    def is_ancestor(self, older: str, newer: str) -> bool:
        result = run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=self.root,
            check=False,
            capture=True,
        )
        if result.returncode not in (0, 1):
            raise subprocess.CalledProcessError(
                result.returncode, result.args, stderr=result.stderr
            )
        return result.returncode == 0

    def adds_nothing(self, ref: str, target: str) -> bool:
        """True when merging ``ref`` into ``target`` would leave its tree unchanged.

        Decided by content, not ancestry: a squash-merged branch, or a stale copy
        of an upstream that was rebased and force-pushed elsewhere, shares no
        commits with ``target`` even though every change it carries is already
        there. A conflict, unrelated histories, or a git older than 2.38 (no
        ``--write-tree``) all answer False, so doubt never discards anything.
        """
        merged = run(
            ["git", "merge-tree", "--write-tree", target, ref],
            cwd=self.root,
            check=False,
            capture=True,
        )
        if merged.returncode or not merged.stdout:
            return False
        tree = merged.stdout.splitlines()[0]
        return tree == run_output(["git", "rev-parse", f"{target}^{{tree}}"], cwd=self.root)

    def keep_gone(self, branch: str, upstream: str) -> None:
        # Usually a merged PR whose remote branch was deleted, or one closed
        # unmerged. Nothing is left to pull, so it is not a failure; keep it
        # for the user to review.
        info(f"  🪦 Upstream gone: {branch} ({upstream}); branch and worktree retained")
        self.gone.append(branch)

    def save_wip(self, branch: str, path: Path) -> str:
        if not self.dirty(path):
            return ""
        # A superproject stash cannot preserve dirty submodule working copies.
        submodules = run(
            ["git", "submodule", "foreach", "--quiet", "--recursive", "git status --porcelain"],
            cwd=path,
            check=False,
            capture=True,
        )
        if submodules.returncode or submodules.stdout:
            raise OSError(f"dirty/unreadable submodule in {path}; left untouched")
        before = run_output(["git", "rev-parse", "--verify", "refs/stash"], cwd=path, check=False)
        run(
            [
                "git",
                "stash",
                "push",
                "--include-untracked",
                "--message",
                f"che sync-all-branches: {branch}",
                "--",
                *self.pathspecs(path),
            ],
            cwd=path,
        )
        oid = run_output(["git", "rev-parse", "--verify", "refs/stash"], cwd=path)
        if not oid or oid == before:
            raise OSError(
                f"could not verify a new recovery stash in {path}; inspect git stash list"
            )
        info(f"  🧺 Recovery stash for {branch} in {path}: {oid}")
        if self.dirty(path):
            raise OSError(f"worktree remains dirty; left untouched, recovery stash {oid} in {path}")
        return oid

    def restore_wip(self, branch: str, path: Path, oid: str) -> bool:
        if not oid:
            return True
        # Worktrees share refs/stash. Never pop the latest entry or drop a
        # recovery copy until both working-copy and index restoration succeed.
        if run(["git", "stash", "apply", "--index", oid], cwd=path, check=False).returncode:
            self.block(
                branch, f"WIP restoration conflicted in {path}; recovery stash retained: {oid}"
            )
            return False
        entries = run_output(["git", "stash", "list", "--format=%gd%x01%H"], cwd=path)
        matching = next(
            (
                ref
                for line in entries.splitlines()
                for ref, sha in [line.split("\x01")]
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
        self.restored.append(branch)
        return True

    def sync_branch(self, branch: str, upstream: str, occupied: dict[str, Path]) -> None:
        path = occupied.get(branch)
        if path is not None:
            if not path.is_dir():
                self.block(branch, f"worktree unavailable: {path}")
                return
            if in_progress(path):
                self.block(branch, f"operation in progress in {path}; left untouched")
                return
        if self.includes(branch, upstream):
            info(f"  = Up to date: {branch} (local commits kept){f' in {path}' if path else ''}")
            self.current.append(branch)
            return
        # Replaying commits whose content the upstream already holds conflicts
        # for nothing: the usual cause is a parent branch squash-merged into main
        # and this branch rebased and force-pushed from another machine. When a
        # diverged branch adds nothing to its upstream, moving it there discards
        # no change. A branch merely behind fast-forwards through the rebase.
        local = f"refs/heads/{branch}"
        stale = not self.is_ancestor(local, upstream) and self.adds_nothing(local, upstream)
        if self.dry_run:
            action = (
                f"reset {branch} to {upstream} (its changes are already there)"
                if stale
                else f"update {branch} from {upstream}"
            )
            info(f"  🌵 Would {action}{f' in {path}' if path else ''}; stash/restore WIP if needed")
            return

        temporary: Path | None = None
        oid = ""
        try:
            if path is None:
                temporary = Path(tempfile.mkdtemp(prefix=TEMPORARY_PREFIX))
                path = temporary / "checkout"
                run(["git", "worktree", "add", "--quiet", str(path), branch], cwd=self.root)
            oid = self.save_wip(branch, path)
            if stale:
                info(
                    f"⏩ Resetting {branch} to {upstream} in {path}; its changes are already there"
                )
                # --keep, not --hard: WIP is already stashed, and --keep refuses
                # rather than overwrite anything that slipped past the stash.
                moved = (
                    run(
                        ["git", "reset", "--quiet", "--keep", upstream], cwd=path, check=False
                    ).returncode
                    == 0
                )
                if not moved:
                    warning(f"  ❌ Reset failed for {branch} in {path}")
                    self.block(branch, f"reset failed in {path}; original commits retained")
                restored = self.restore_wip(branch, path, oid)
                if moved and restored:
                    if self.includes(branch, upstream):
                        self.reset.append(branch)
                        success(f"  ✅ Reset to upstream: {branch}")
                    else:
                        self.block(branch, "verification failed: fetched upstream not included")
                return
            info(f"⬇️ Rebasing {branch} in {path} (lock preserved)")
            # DELIBERATE DIVERGENCE: one fetched snapshot instead of pull's
            # per-branch fetch. Disable autostash/updateRefs so Git cannot
            # compete with our exact WIP recovery or move unrelated branches.
            # --fork-point is what `git pull --rebase` does and what a bare
            # `git rebase <upstream>` does not: it reads the upstream's reflog
            # to find where this branch left it, so after a force-push from
            # another machine only the commits made here are replayed, not the
            # dozens the upstream rewrote (which conflict for nothing).
            rebased = (
                run(
                    [
                        "git",
                        "-c",
                        "rebase.autoStash=false",
                        "-c",
                        "rebase.updateRefs=false",
                        "rebase",
                        "--no-autostash",
                        "--fork-point",
                        upstream,
                    ],
                    cwd=path,
                    check=False,
                ).returncode
                == 0
            )
            if not rebased:
                warning(f"  ❌ Rebase failed for {branch} in {path}")
                if in_progress(path):
                    # Abort only the rebase we started. Failure to abort is
                    # fatal: applying WIP or continuing is no longer safe.
                    abort = run(["git", "rebase", "--abort"], cwd=path, check=False)
                    if abort.returncode:
                        warning(f"STOP: cannot abort in {path}; recovery stash: {oid or 'none'}")
                        raise SystemExit(1)
                self.block(branch, f"rebase failed in {path}; original commits retained")
            restored = self.restore_wip(branch, path, oid)
            if rebased and restored:
                if self.includes(branch, upstream):
                    self.updated.append(branch)
                    success(f"  ✅ Updated: {branch}")
                else:
                    self.block(branch, "verification failed: fetched upstream not included")
        except (subprocess.CalledProcessError, OSError) as exc:
            self.block(
                branch, f"{exc}; inspect {path}; recovery stash: {oid or 'see git stash list'}"
            )
        except KeyboardInterrupt:
            warning(
                f"Interrupted in {path}; inspect status before resuming. Recovery stash: {oid or 'see git stash list'}"
            )
            raise
        finally:
            # Never use TemporaryDirectory here: its automatic recursive
            # deletion would erase files if a hook or recovery left a dirty tree.
            if temporary is not None:
                if not (temporary / "checkout").exists():
                    temporary.rmdir()
                elif (
                    not in_progress(temporary / "checkout")
                    and run(
                        ["git", "worktree", "remove", str(temporary / "checkout")],
                        cwd=self.root,
                        check=False,
                    ).returncode
                    == 0
                ):
                    temporary.rmdir()
                else:
                    self.block(
                        branch,
                        f"temporary worktree retained for inspection: {temporary / 'checkout'}",
                    )

    def bases(self) -> list[str]:
        return [ref for name in BASE_BRANCHES if self.has_ref(ref := f"refs/remotes/origin/{name}")]

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
        ref = ref or f"refs/heads/{branch}"
        tip = run_output(["git", "rev-parse", "--verify", ref], cwd=self.root)
        for base in self.bases():
            label = base.removeprefix("refs/remotes/")
            if (
                run(
                    ["git", "merge-base", "--is-ancestor", tip, base],
                    cwd=self.root,
                    check=False,
                    capture=True,
                ).returncode
                == 0
            ):
                return f"contained in {label}"
            if self.adds_nothing(tip, base):
                return f"its content is already in {label}"
            fork = run_output(["git", "merge-base", base, tip], cwd=self.root, check=False)
            if not fork:
                continue
            probe = run_output(
                ["git", "commit-tree", f"{tip}^{{tree}}", "-p", fork, "-m", "che squash probe"],
                cwd=self.root,
                check=False,
            )
            if probe:
                cherry = run_output(["git", "cherry", base, probe], cwd=self.root, check=False)
                if cherry.startswith("-"):
                    return f"squash-merged into {label}"
        return self.merged_pull_request(branch, tip) if github else ""

    def merged_pull_request(self, branch: str, tip: str) -> str:
        origin = run_output(["git", "remote", "get-url", "origin"], cwd=self.root, check=False)
        # The patch-ID proofs work from cached refs; this one is a network call.
        if self.dry_run or "github.com" not in origin or shutil.which("gh") is None:
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
        tip_time = int(run_output(["git", "log", "-1", "--format=%ct", tip], cwd=self.root))
        for pull in pulls:
            contains = (
                run(
                    ["git", "merge-base", "--is-ancestor", tip, pull["headRefOid"]],
                    cwd=self.root,
                    check=False,
                    capture=True,
                ).returncode
                == 0
            )
            merged_at = datetime.fromisoformat(pull["mergedAt"]).timestamp()
            if contains or tip_time <= merged_at:
                return f"PR #{pull['number']} merged"
        return ""

    def checked_out_here(self, tree: Worktree) -> bool:
        path = Path(tree.path).resolve()
        return path in (self.root.resolve(), Path(self.trees[0].path).resolve())

    def proven_merged(self, branch: str, upstream: str, *, gone: bool) -> str:
        """Why ``branch`` counts as merged into a main or dev branch, or "".

        With its upstream still on origin, the upstream must be merged too, so
        commits pushed from elsewhere are never dropped. A branch sitting on a
        base's tip has nothing to merge yet; that is a new branch, not a merged one.
        """
        if branch in PROTECTED_BRANCHES:
            return ""
        if gone:
            return self.merged_reason(branch)
        tip = run_output(["git", "rev-parse", "--verify", f"refs/heads/{branch}"], cwd=self.root)
        if any(
            tip == run_output(["git", "rev-parse", "--verify", base], cwd=self.root)
            for base in self.bases()
        ):
            return ""
        reason = self.merged_reason(branch)
        if not reason or self.is_ancestor(upstream, f"refs/heads/{branch}"):
            return reason
        return reason if self.merged_reason(branch, upstream) else ""

    def drop_merged(self, branch: str, reason: str, occupied: dict[str, Path]) -> None:
        """Delete merged ``branch`` and its worktree, keeping any uncommitted work.

        DELIBERATE DIVERGENCE: only a merged branch whose upstream was gone used
        to be deleted, and its worktree was kept when dirty or mid-operation.
        Now any branch proven merged into a main or dev branch goes, upstream or
        not. Its worktree goes with it: a lock is dropped, an operation in
        progress is aborted (which leaves the branch where it was) and
        uncommitted work is stashed, so `git stash list` keeps it. Only the
        caller's own checkout, which cannot be removed from under it, stays.
        """
        tip = run_output(["git", "rev-parse", "--short", f"refs/heads/{branch}"], cwd=self.root)
        path = occupied.get(branch)
        tree = next((t for t in self.trees if path and Path(t.path) == path), None)
        if tree is not None and self.checked_out_here(tree):
            info(f"  ⏭️ Merged, kept: {branch} ({reason}; checked out here)")
            self.merged_kept.append(f"{branch}: checked out here")
            return
        if self.dry_run:
            where = f" and its worktree {tree.path}" if tree is not None else ""
            info(f"  🌵 Would delete merged: {branch} at {tip}{where} ({reason})")
            return
        if tree is not None:
            worktree = Path(tree.path)
            if tree.locked:
                run(["git", "worktree", "unlock", tree.path], cwd=self.root, check=False)
            if worktree.is_dir():
                if in_progress(worktree) and not abort_operation(worktree):
                    self.block(
                        branch, f"merged ({reason}) but cannot abort the operation in {worktree}"
                    )
                    return
                try:
                    stash = stash_everything(worktree, f"che sync-all-branches: {branch} (merged)")
                except (subprocess.CalledProcessError, OSError) as exc:
                    self.block(branch, f"merged ({reason}) but {exc}")
                    return
                if stash:
                    info(f"  🧺 Stashed uncommitted work of {branch}: {stash}")
                    self.stashed.append(f"{branch}: {stash}")
            removed = run(
                ["git", "worktree", "remove", "--force", tree.path],
                cwd=self.root,
                check=False,
            )
            if removed.returncode:
                self.block(branch, f"merged ({reason}) but worktree removal refused: {tree.path}")
                return
        if run(["git", "branch", "-D", branch], cwd=self.root, check=False).returncode:
            self.block(branch, f"merged ({reason}) but branch deletion failed")
            return
        self.deleted.append(branch)
        success(
            f"  🗑️ Deleted merged: {branch} at {tip} ({reason}) - restore with: git branch {branch} {tip}"
        )

    def clear_leftovers(self) -> None:
        """Remove disposable worktrees an interrupted earlier sync left behind.

        A sync killed mid-rebase leaves its temporary checkout holding the
        branch, so every later run reports that branch blocked. Aborting the
        rebase puts the branch back where it was; the checkout itself was never
        the user's workspace.
        """
        leftovers = [
            tree
            for tree in self.trees[1:]
            if Path(tree.path).name == "checkout"
            and Path(tree.path).parent.name.startswith(TEMPORARY_PREFIX)
        ]
        for tree in leftovers:
            path = Path(tree.path)
            if self.dry_run:
                info(f"  🌵 Would clear a leftover sync checkout: {path}")
                continue
            info(f"  🧹 Clearing a leftover sync checkout: {path}")
            if path.is_dir() and in_progress(path) and not abort_operation(path):
                self.block(path.name, f"cannot abort the operation in leftover {path}")
                continue
            if run(
                ["git", "worktree", "remove", "--force", str(path)], cwd=self.root, check=False
            ).returncode:
                self.block(str(path), "leftover sync checkout could not be removed")
                continue
            if path.parent.is_dir() and not any(path.parent.iterdir()):
                path.parent.rmdir()
        if leftovers and not self.dry_run:
            self.trees = worktrees(self.root)

    def update(self) -> None:
        self.clear_leftovers()
        occupied = self.occupied()
        for branch, upstream in local_branches("upstream", cwd=self.root):
            if not upstream and self.has_ref(f"refs/remotes/origin/{branch}"):
                upstream = f"refs/remotes/origin/{branch}"
            if not upstream:
                info(f"  ℹ️ Local only: {branch} (no remote counterpart)")  # noqa: RUF001
                self.local_only.append(branch)
                continue
            try:
                gone = not self.has_ref(upstream)
                if reason := self.proven_merged(branch, upstream, gone=gone):
                    self.drop_merged(branch, reason, occupied)
                elif gone:
                    if branch in PROTECTED_BRANCHES:
                        info(f"  🛡️ Protected: {branch} (upstream gone)")
                    else:
                        self.keep_gone(branch, upstream)
                else:
                    self.sync_branch(branch, upstream, occupied)
            except (subprocess.CalledProcessError, OSError) as exc:
                self.block(branch, f"preflight failed: {exc}")

    def summary(self, tracked: list[str]) -> None:
        success("═══ summary ═══")
        for label, names in (
            ("Updated", self.updated),
            ("Reset to upstream", self.reset),
            ("Up to date", self.current),
            ("Deleted (merged)", self.deleted),
            ("Tracked new", tracked),
            ("Local only", self.local_only),
            ("Upstream gone", self.gone),
            ("WIP restored", self.restored),
        ):
            info(f"{label}: {len(names)} ({', '.join(names)})")
        if self.gone:
            info("  Review them; clean-stale-branches removes them once you are sure.")
        info(f"Stashed from merged worktrees: {len(self.stashed)}")
        for entry in self.stashed:
            info(f"  • {entry}")
        info(f"Merged, kept: {len(self.merged_kept)}")
        for reason in self.merged_kept:
            info(f"  • {reason}")
        info(f"Blocked: {len(self.blocked)}")
        for reason in self.blocked:
            warning(f"  • {reason}")
        info("Caller checkout, unmerged branches and every local change preserved. Nothing pushed.")
