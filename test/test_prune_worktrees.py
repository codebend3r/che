"""End-to-end tests for ``bin/git/prune-worktrees.py``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest
from conftest import git

PRUNE = "git/prune-worktrees.py"


class Repo(NamedTuple):
    work: Path
    linked: Path
    hook_log: Path


@pytest.fixture
def repo(git_repo: Callable[[str], Path], tmp_path: Path) -> Repo:
    """A main clone left on ``feature``, one linked worktree, and a
    post-checkout hook that logs when it fires."""
    work = git_repo("work")
    git(work, "checkout", "--quiet", "-b", "feature")
    linked = tmp_path / "wt-linked"
    git(work, "worktree", "add", "--quiet", "-b", "linked", str(linked), "main")

    hook_log = tmp_path / "hooks.log"
    hook = work / ".git" / "hooks" / "post-checkout"
    hook.write_text(f'#!/bin/sh\necho post-checkout >> "{hook_log}"\n')
    hook.chmod(0o755)
    return Repo(work=work, linked=linked, hook_log=hook_log)


def test_removes_linked_worktrees_and_parks_main(repo: Repo, run_script):
    result = run_script(PRUNE, ["--dry-run=false"], cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not repo.linked.exists()
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "main"
    assert "Switching main worktree to 🌿 main (from feature)" in result.stdout


def test_parking_runs_no_hooks(repo: Repo, run_script):
    result = run_script(PRUNE, ["--dry-run=false"], cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not repo.hook_log.exists()


def test_run_from_the_linked_worktree_parks_the_main_one(repo: Repo, run_script):
    result = run_script(PRUNE, ["--dry-run=false"], cwd=repo.linked)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not repo.linked.exists()
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "main"


def test_dry_run_is_the_default_and_changes_nothing(repo: Repo, run_script):
    result = run_script(PRUNE, cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 worktree(s) would be removed" in result.stdout
    assert repo.linked.is_dir()
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "feature"


def test_refuses_over_uncommitted_changes_in_the_main_worktree(repo: Repo, run_script):
    (repo.work / "README.md").write_text("in progress\n")

    result = run_script(PRUNE, ["--dry-run=false"], cwd=repo.work)

    assert result.returncode == 1
    assert "commit or stash before you prune" in result.stdout
    assert repo.linked.is_dir()
