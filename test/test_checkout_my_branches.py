"""End-to-end tests for ``bin/git/checkout-my-branches.py``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import EMAIL, git, local_branches

CHECKOUT = "git/checkout-my-branches.py"


@pytest.fixture
def work(git_repo: Callable[[str], Path]) -> Path:
    """A clone on ``main``; origin also has ``mine`` (by EMAIL), ``feat/nested``
    (by EMAIL) and ``theirs`` (by someone else), none of them local."""
    other = git_repo("other")
    for branch, email in (
        ("mine", EMAIL),
        ("feat/nested", EMAIL),
        ("theirs", "someone@example.com"),
    ):
        git(other, "checkout", "--quiet", "-b", branch, "main")
        git(other, "-c", f"user.email={email}", "commit", "--quiet", "--allow-empty", "-m", branch)
        git(other, "push", "--quiet", "origin", branch)
    return git_repo("work")


def test_creates_your_remote_branches_without_switching_to_them(work: Path, run_script):
    result = run_script(CHECKOUT, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert local_branches(work) == ["feat/nested", "main", "mine"]
    assert git(work, "rev-parse", "--abbrev-ref", "mine@{upstream}") == "origin/mine"
    assert git(work, "rev-parse", "--abbrev-ref", "feat/nested@{upstream}") == (
        "origin/feat/nested"
    )
    assert git(work, "symbolic-ref", "--short", "HEAD") == "main"
    assert "👻  Skipped (not yours): 1" in result.stdout


def test_a_dirty_tree_does_not_block(work: Path, run_script):
    """Nothing is checked out any more, so uncommitted work is never at risk."""
    (work / "README.md").write_text("in progress\n")

    result = run_script(CHECKOUT, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "mine" in local_branches(work)
    assert (work / "README.md").read_text() == "in progress\n"


def test_an_existing_branch_is_reported_as_already_local(work: Path, run_script):
    git(work, "branch", "--quiet", "mine", "origin/mine")

    result = run_script(CHECKOUT, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "⏭️  Already local: mine" in result.stdout
    assert "🆕 Checking out: mine" not in result.stdout


def test_a_local_branch_named_like_a_tag_counts_as_local(work: Path, run_script):
    """refname:short reads `heads/mine` once a tag `mine` exists, so the
    branch looked missing and `git branch --track mine` failed."""
    git(work, "branch", "--quiet", "mine", "origin/mine")
    git(work, "tag", "mine", "origin/mine")

    result = run_script(CHECKOUT, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "⏭️  Already local: mine" in result.stdout


def test_author_defaults_to_the_git_config_email(work: Path, run_script):
    git(work, "config", "user.email", "someone@example.com")

    result = run_script(CHECKOUT, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "for author 👤 someone@example.com" in result.stdout
    assert local_branches(work) == ["main", "theirs"]


def test_limit_must_be_positive(work: Path, run_script):
    result = run_script(CHECKOUT, ["--limit=0"], cwd=work)

    assert result.returncode == 1
    assert "--limit must be a positive integer (got: 0)" in result.stdout
