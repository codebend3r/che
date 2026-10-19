"""End-to-end tests for ``bin/git/hard-reset-all-branches.py``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import commit, git, local_branches

RESET = "git/hard-reset-all-branches.py"
REAL = {"DRY_RUN": "false"}


def sha(cwd: Path, ref: str) -> str:
    return git(cwd, "rev-parse", ref)


@pytest.fixture
def work(git_repo: Callable[[str], Path]) -> Path:
    """A clone, left on ``main``, where every branch has drifted from origin.

    ``feature`` carries a local-only commit, ``main`` is behind a commit pushed
    from another clone, and ``local-only`` was never pushed at all.
    """
    work = git_repo("work")
    git(work, "checkout", "--quiet", "-b", "feature", "main")
    git(work, "push", "--quiet", "--set-upstream", "origin", "feature")
    commit(work, "unpushed.txt")
    git(work, "checkout", "--quiet", "-b", "local-only", "main")
    commit(work, "never-pushed.txt")
    git(work, "checkout", "--quiet", "main")

    other = git_repo("other")
    commit(other, "upstream.txt")
    git(other, "push", "--quiet", "origin", "main")
    return work


def test_resets_every_branch_to_origin_and_returns(work: Path, run_script):
    result = run_script(RESET, cwd=work, env=REAL)

    assert result.returncode == 0, result.stdout + result.stderr
    assert sha(work, "feature") == sha(work, "origin/feature")
    assert sha(work, "main") == sha(work, "origin/main")
    assert (work / "upstream.txt").exists()
    assert git(work, "branch", "--show-current") == "main"
    assert "Reset:    2" in result.stdout


def test_a_branch_without_origin_is_left_alone(work: Path, run_script):
    before = sha(work, "local-only")

    result = run_script(RESET, cwd=work, env=REAL)

    assert result.returncode == 0, result.stdout + result.stderr
    assert sha(work, "local-only") == before
    assert "• 🌿 local-only" in result.stdout


def test_dry_run_changes_nothing(work: Path, run_script):
    before = {branch: sha(work, branch) for branch in local_branches(work)}

    result = run_script(RESET, cwd=work, env={"DRY_RUN": "true"})

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 branch(es) would be hard reset" in result.stdout
    assert "feature — drops 1 local commit(s)" in result.stdout
    assert "main — picks up 1 from origin" in result.stdout
    assert {branch: sha(work, branch) for branch in local_branches(work)} == before


def test_previews_unless_told_otherwise(work: Path, run_script):
    before = sha(work, "feature")

    result = run_script(RESET, cwd=work, env={"DRY_RUN": ""})

    assert result.returncode == 0, result.stdout + result.stderr
    assert "would be hard reset" in result.stdout
    assert sha(work, "feature") == before


def test_a_dirty_tree_refuses_without_force(work: Path, run_script):
    (work / "README.md").write_text("edited\n")
    before = sha(work, "feature")

    result = run_script(RESET, cwd=work, env=REAL)

    assert result.returncode == 1
    assert "Working tree is dirty" in result.stdout
    assert (work / "README.md").read_text() == "edited\n"
    assert sha(work, "feature") == before


def test_force_discards_uncommitted_changes(work: Path, run_script):
    (work / "README.md").write_text("edited\n")

    result = run_script(RESET, ["--force"], cwd=work, env=REAL)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (work / "README.md").read_text() == "hello\n"
    assert sha(work, "feature") == sha(work, "origin/feature")


def test_untracked_files_survive(work: Path, run_script):
    (work / "scratch.txt").write_text("mine\n")

    result = run_script(RESET, cwd=work, env=REAL)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (work / "scratch.txt").read_text() == "mine\n"


def test_a_branch_in_another_worktree_is_reset_there(work: Path, tmp_path: Path, run_script):
    linked = tmp_path / "feature-wt"
    git(work, "worktree", "add", "--quiet", str(linked), "feature")

    result = run_script(RESET, cwd=work, env=REAL)

    assert result.returncode == 0, result.stdout + result.stderr
    assert sha(work, "feature") == sha(work, "origin/feature")
    assert not (linked / "unpushed.txt").exists()
    assert git(linked, "branch", "--show-current") == "feature"


def test_a_dirty_worktree_is_skipped(work: Path, tmp_path: Path, run_script):
    linked = tmp_path / "feature-wt"
    git(work, "worktree", "add", "--quiet", str(linked), "feature")
    (linked / "README.md").write_text("in progress\n")
    before = sha(work, "feature")

    result = run_script(RESET, cwd=work, env=REAL)

    assert result.returncode == 0, result.stdout + result.stderr
    assert sha(work, "feature") == before
    assert (linked / "README.md").read_text() == "in progress\n"
    assert "feature (dirty worktree)" in result.stdout
    assert sha(work, "main") == sha(work, "origin/main")


def test_nothing_to_do_when_everything_matches(git_repo: Callable[[str], Path], run_script):
    work = git_repo("work")

    result = run_script(RESET, cwd=work, env=REAL)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "already match it" in result.stdout
