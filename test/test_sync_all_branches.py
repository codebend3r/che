"""End-to-end tests for ``bin/git/sync-all-branches.py``.

The sync only deletes merged branches, rebases tracked ones and checks out new
ones. None of that is the user committing or pushing, so no repo hook (a
lefthook or husky pre-commit, pre-push, post-checkout) may run, nothing may be
pushed, and every worktree stays where it is. The repo below gives every step
something to do, with a hook of every kind that logs when it fires.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from conftest import BIN

EMAIL = "test@example.com"

HOOKS = (
    "pre-commit",
    "prepare-commit-msg",
    "commit-msg",
    "post-commit",
    "pre-rebase",
    "post-rewrite",
    "post-checkout",
    "post-merge",
    "pre-push",
)


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def clone(origin: Path, path: Path) -> Path:
    git(origin.parent, "clone", "--quiet", str(origin), str(path))
    git(path, "config", "user.email", EMAIL)
    git(path, "config", "user.name", "Test")
    return path


def commit(cwd: Path, name: str) -> None:
    (cwd / name).write_text(f"{name}\n")
    git(cwd, "add", name)
    git(cwd, "commit", "--quiet", "-m", name)


class Repo(NamedTuple):
    origin: Path
    work: Path
    wip: Path
    shipped: Path
    hook_log: Path


def build_repo(tmp_path: Path) -> Repo:
    """A clone, its origin, and two linked worktrees.

    ``work`` is on main and has, by the time the sync runs:
      - ``stale``: pushed, then deleted on origin
      - ``behind``: origin moved on, and a local commit must be replayed
      - ``wip``: checked out in a linked worktree with an unpushed commit
      - ``shipped``: checked out in a clean linked worktree, fully pushed
      - ``mine``: on origin only, authored by ``EMAIL``
    """
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git(origin, "init", "--bare", "--initial-branch=main", "--quiet")

    work = clone(origin, tmp_path / "work")
    commit(work, "init")
    git(work, "push", "--quiet", "origin", "main")

    for branch in ("stale", "behind", "shipped", "mine"):
        git(work, "checkout", "--quiet", "-b", branch, "main")
        commit(work, branch)
        git(work, "push", "--quiet", "--set-upstream", "origin", branch)
    git(work, "checkout", "--quiet", "main")
    git(work, "branch", "--quiet", "-D", "mine")

    other = clone(origin, tmp_path / "other")
    git(other, "push", "--quiet", "origin", "--delete", "stale")
    git(other, "checkout", "--quiet", "behind")
    commit(other, "behind-upstream")
    git(other, "push", "--quiet")

    git(work, "checkout", "--quiet", "behind")
    commit(work, "behind-local")
    git(work, "checkout", "--quiet", "main")

    wip = tmp_path / "wip"
    git(work, "worktree", "add", "--quiet", "-b", "wip", str(wip), "main")
    commit(wip, "wip")

    shipped = tmp_path / "shipped"
    git(work, "worktree", "add", "--quiet", str(shipped), "shipped")

    hook_log = tmp_path / "hooks.log"
    for hook in HOOKS:
        path = work / ".git" / "hooks" / hook
        path.write_text(f'#!/bin/sh\necho {hook} >> "{hook_log}"\n')
        path.chmod(0o755)

    return Repo(origin=origin, work=work, wip=wip, shipped=shipped, hook_log=hook_log)


def worktree_paths(work: Path) -> list[str]:
    porcelain = git(work, "worktree", "list", "--porcelain").splitlines()
    return [line for line in porcelain if line.startswith("worktree ")]


def sync(work: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BIN / "git" / "sync-all-branches.py")],
        cwd=work,
        capture_output=True,
        text=True,
        check=False,
        # A HOME of its own keeps the user's global git config (pull.rebase,
        # hooksPath, aliases) out of the run.
        env={**os.environ, "HOME": str(work.parent), "NO_COLOR": "1"},
    )


def test_sync_runs_no_hooks(tmp_path: Path):
    repo = build_repo(tmp_path)

    result = sync(repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    fired = repo.hook_log.read_text().split() if repo.hook_log.exists() else []
    assert fired == []


def test_sync_never_pushes(tmp_path: Path):
    repo = build_repo(tmp_path)

    result = sync(repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo.origin, "branch", "--list", "wip") == ""


def test_sync_leaves_every_worktree_in_place(tmp_path: Path):
    repo = build_repo(tmp_path)
    before = worktree_paths(repo.work)

    result = sync(repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert repo.wip.is_dir()
    assert repo.shipped.is_dir()
    assert worktree_paths(repo.work) == before


def test_sync_still_tidies_every_branch(tmp_path: Path):
    repo = build_repo(tmp_path)
    work = repo.work

    result = sync(work)

    assert result.returncode == 0, result.stdout + result.stderr
    local = git(work, "for-each-ref", "--format=%(refname:short)", "refs/heads").split()
    assert "stale" not in local
    assert "mine" in local
    git(work, "merge-base", "--is-ancestor", "origin/behind", "behind")


def test_a_dirty_worktree_is_skipped_not_fatal(tmp_path: Path):
    repo = build_repo(tmp_path)
    scratch = repo.shipped / "scratch.txt"
    scratch.write_text("in progress\n")

    result = sync(repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert scratch.read_text() == "in progress\n"
    local = git(repo.work, "for-each-ref", "--format=%(refname:short)", "refs/heads").split()
    assert "mine" in local
