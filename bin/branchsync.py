"""Non-destructive branch/worktree synchronization for sync-all-branches.

Unlike the old delegated cleanup, sync preserves every checkout and every local
change. A branch is only moved past its own commits or deleted when a content
check proves its changes are already upstream or in main. Only disposable
worktrees created here may be removed. Git locks need no special handling: they
prevent removal/pruning, not a rebase inside the locked checkout.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from gitutils import Worktree, find_main_branch, local_branches, worktrees
from utils import info, run, run_output, success, warning

_OPERATION_FILES = (
    "rebase-merge",
    "rebase-apply",
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "BISECT_START",
)


def git_path(path: Path, name: str) -> Path:
    result = Path(run_output(["git", "rev-parse", "--git-path", name], cwd=path))
    return result if result.is_absolute() else path / result


def operation_branch(path: Path) -> str:
    """A rebase/bisect detaches HEAD but still reserves its original branch."""
    for name in ("rebase-merge/head-name", "rebase-apply/head-name", "BISECT_START"):
        file = git_path(path, name)
        if file.is_file():
            return file.read_text().splitlines()[0].removeprefix("refs/heads/")
    return ""


def in_progress(path: Path) -> bool:
    return any(git_path(path, name).exists() for name in _OPERATION_FILES)


@dataclass
class BranchSync:
    root: Path
    dry_run: bool
    updated: list[str] = field(default_factory=list)
    current: list[str] = field(default_factory=list)
    local_only: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    reset: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    trees: list[Worktree] = field(init=False)
    main: str = field(init=False)

    def __post_init__(self) -> None:
        self.trees = worktrees(self.root)
        self.main = find_main_branch(self.root)

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

    def adds_nothing(self, branch: str, target: str) -> bool:
        """True when merging ``branch`` into ``target`` would leave its tree unchanged.

        Decided by content, not ancestry: a squash-merged branch, or a stale copy
        of an upstream that was rebased and force-pushed elsewhere, shares no
        commits with ``target`` even though every change it carries is already
        there. A conflict, unrelated histories, or a git older than 2.38 (no
        ``--write-tree``) all answer False, so doubt never discards anything.
        """
        merged = run(
            ["git", "merge-tree", "--write-tree", target, f"refs/heads/{branch}"],
            cwd=self.root,
            check=False,
            capture=True,
        )
        if merged.returncode or not merged.stdout:
            return False
        tree = merged.stdout.splitlines()[0]
        return tree == run_output(["git", "rev-parse", f"{target}^{{tree}}"], cwd=self.root)

    def drop_gone(self, branch: str, upstream: str, occupied: dict[str, Path]) -> None:
        """Delete a branch whose upstream is gone, but only once main holds its work.

        A deleted remote branch is not proof of a merge (a PR can be closed
        unmerged), so the gate is content in origin's main, never the gone ref.
        """
        main = f"refs/remotes/origin/{self.main}"
        if not self.main or branch == self.main or not self.has_ref(main):
            self.block(branch, f"upstream gone: {upstream}; no origin main to compare; retained")
            return
        if not self.adds_nothing(branch, main):
            self.block(branch, f"upstream gone: {upstream}; not merged into {self.main}; retained")
            return
        if branch in occupied:
            self.block(
                branch,
                f"upstream gone and merged into {self.main}, but checked out in {occupied[branch]}; retained",
            )
            return
        if self.dry_run:
            info(f"  🌵 Would delete {branch}: upstream gone, work already in {self.main}")
            return
        if run(["git", "branch", "--quiet", "-D", branch], cwd=self.root, check=False).returncode:
            self.block(
                branch, f"upstream gone and merged into {self.main}, but could not delete it"
            )
            return
        self.deleted.append(branch)
        success(f"  🗑️ Deleted: {branch} (upstream gone, work already in {self.main})")

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
        stale = not self.is_ancestor(f"refs/heads/{branch}", upstream) and self.adds_nothing(
            branch, upstream
        )
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
                temporary = Path(tempfile.mkdtemp(prefix="che-sync-"))
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

    def update(self) -> None:
        occupied = self.occupied()
        for branch, upstream in local_branches("upstream", cwd=self.root):
            if not upstream and self.has_ref(f"refs/remotes/origin/{branch}"):
                upstream = f"refs/remotes/origin/{branch}"
            if not upstream:
                info(f"  ℹ️ Local only: {branch} (no remote counterpart)")  # noqa: RUF001
                self.local_only.append(branch)
                continue
            try:
                if not self.has_ref(upstream):
                    self.drop_gone(branch, upstream, occupied)
                    continue
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
            ("WIP restored", self.restored),
        ):
            info(f"{label}: {len(names)} ({', '.join(names)})")
        info(f"Blocked: {len(self.blocked)}")
        for reason in self.blocked:
            warning(f"  • {reason}")
        info(
            "Caller checkout, existing worktree paths, locks and every local change preserved. Nothing pushed."
        )
