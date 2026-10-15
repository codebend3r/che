"""End-to-end tests for ``bin/git/clean-stale-branches.py``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import git, local_branches

CLEAN = "git/clean-stale-branches.py"


@pytest.fixture
def work(git_repo: Callable[[str], Path]) -> Path:
    """A clone whose ``gone`` and ``also-gone`` were deleted on origin, and
    whose ``live`` still exists there. It is left on ``main``."""
    work = git_repo("work")
    for branch in ("gone", "also-gone", "live"):
        git(work, "checkout", "--quiet", "-b", branch, "main")
        git(work, "push", "--quiet", "--set-upstream", "origin", branch)
    git(work, "checkout", "--quiet", "main")
    git(work, "push", "--quiet", "origin", "--delete", "gone", "also-gone")
    return work


def test_deletes_branches_whose_upstream_is_gone(work: Path, run_script):
    result = run_script(CLEAN, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert local_branches(work) == ["live", "main"]


def test_a_stale_current_branch_is_reported_with_the_checked_out_ones(work: Path, run_script):
    """It is pinned by its worktree like any other checked-out branch."""
    git(work, "checkout", "--quiet", "gone")

    result = run_script(CLEAN, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 stale branch(es) are checked out in a worktree" in result.stdout
    assert "• 🌿 gone (in " in result.stdout
    assert local_branches(work) == ["gone", "live", "main"]


def test_a_current_branch_that_is_not_stale_goes_unmentioned(work: Path, run_script):
    """The scan used to announce "Skipping current branch" for any branch you
    were on, stale or not."""
    git(work, "checkout", "--quiet", "live")

    result = run_script(CLEAN, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "live" not in result.stdout
    assert "live" in local_branches(work)


def test_a_branch_named_like_a_tag_is_deleted(work: Path, run_script):
    """refname:short reads `heads/gone` once a tag `gone` exists, and
    `git branch -D heads/gone` failed, aborting the whole cleanup."""
    git(work, "tag", "gone", "gone")

    result = run_script(CLEAN, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert local_branches(work) == ["live", "main"]
    assert git(work, "tag", "--list", "gone") == "gone"


def test_dry_run_deletes_nothing(work: Path, run_script):
    result = run_script(CLEAN, ["--dry-run"], cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 stale branch(es) would be deleted" in result.stdout
    assert local_branches(work) == ["also-gone", "gone", "live", "main"]
