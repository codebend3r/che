"""End-to-end tests for ``bin/git/prune-worktrees.py``."""

from __future__ import annotations

import subprocess
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


def test_removes_linked_worktrees_and_leaves_the_main_one_on_its_branch(repo: Repo, run_script):
    result = run_script(PRUNE, ["--dry-run=false"], cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not repo.linked.exists()
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "feature"


def test_pruning_runs_no_hooks(repo: Repo, run_script):
    result = run_script(PRUNE, ["--dry-run=false"], cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not repo.hook_log.exists()


def test_run_from_the_linked_worktree_removes_it(repo: Repo, run_script):
    result = run_script(PRUNE, ["--dry-run=false"], cwd=repo.linked)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not repo.linked.exists()
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "feature"


def test_dry_run_is_the_default_and_changes_nothing(repo: Repo, run_script):
    result = run_script(PRUNE, cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 worktree(s) would be removed" in result.stdout
    assert repo.linked.is_dir()
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "feature"


def test_uncommitted_changes_in_the_main_worktree_do_not_stop_it(repo: Repo, run_script):
    (repo.work / "README.md").write_text("in progress\n")

    result = run_script(PRUNE, ["--dry-run=false"], cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not repo.linked.exists()
    assert (repo.work / "README.md").read_text() == "in progress\n"


def test_a_locked_worktree_is_unlocked_and_removed(repo: Repo, run_script):
    git(repo.work, "worktree", "lock", "--reason", "supacode", str(repo.linked))

    result = run_script(PRUNE, ["--dry-run=false"], cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not repo.linked.exists()


def test_a_dirty_locked_worktree_is_removed_and_its_work_stashed(
    repo: Repo, run_script, tmp_path: Path
):
    other = tmp_path / "wt-other"
    git(repo.work, "worktree", "add", "--quiet", "-b", "other", str(other), "main")
    git(repo.work, "worktree", "lock", str(repo.linked))
    (repo.linked / "scratch.txt").write_text("unsaved\n")
    (repo.linked / "README.md").write_text("edited\n")

    result = run_script(PRUNE, ["--dry-run=false"], cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not other.exists()
    assert not repo.linked.exists()
    assert "che prune-worktrees: linked" in git(repo.work, "stash", "list")
    assert git(repo.work, "show", "stash@{0}:README.md") == "edited"
    assert git(repo.work, "show", "stash@{0}^3:scratch.txt") == "unsaved"


def test_a_worktree_mid_rebase_is_aborted_and_removed(repo: Repo, run_script):
    (repo.linked / "README.md").write_text("linked side\n")
    git(repo.linked, "commit", "--quiet", "-am", "linked side")
    before = git(repo.linked, "rev-parse", "HEAD")
    git(repo.work, "checkout", "--quiet", "-b", "clash", "main")
    (repo.work / "README.md").write_text("clash side\n")
    git(repo.work, "commit", "--quiet", "-am", "clash side")
    rebase = subprocess.run(["git", "rebase", "clash"], cwd=repo.linked, capture_output=True)
    assert rebase.returncode != 0

    result = run_script(PRUNE, ["--dry-run=false"], cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not repo.linked.exists()
    assert git(repo.work, "rev-parse", "linked") == before


def test_force_discards_a_dirty_locked_worktree_without_stashing(repo: Repo, run_script):
    git(repo.work, "worktree", "lock", str(repo.linked))
    (repo.linked / "scratch.txt").write_text("unsaved\n")

    result = run_script(PRUNE, ["--dry-run=false", "--force"], cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not repo.linked.exists()
    assert git(repo.work, "stash", "list") == ""
