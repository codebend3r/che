"""End-to-end tests for ``bin/git/update-local-branches.py``."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import commit, git

UPDATE = "git/update-local-branches.py"


def is_ancestor(cwd: Path, ancestor: str, ref: str) -> bool:
    completed = subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, ref], cwd=cwd)
    return completed.returncode == 0


@pytest.fixture
def work(git_repo: Callable[[str], Path]) -> Path:
    """A clone checked out on ``older``, which origin has moved past.

    ``sub/`` is tracked on every branch, so it survives each checkout. ``older``
    carries the oldest local commit, so the run reaches it after it has
    already checked out ``main`` - the order that exposed the subdirectory bug.
    """
    work = git_repo("work")
    commit(work, "sub/keep.txt")
    git(work, "push", "--quiet")

    git(work, "checkout", "--quiet", "-b", "older", "main")
    commit(work, "older.txt", when="2020-01-01T00:00:00Z")
    git(work, "push", "--quiet", "--set-upstream", "origin", "older")

    other = git_repo("other")
    commit(other, "main-upstream.txt")
    git(other, "push", "--quiet")
    git(other, "checkout", "--quiet", "older")
    commit(other, "older-upstream.txt")
    git(other, "push", "--quiet")

    return work


def test_updates_every_branch(work: Path, run_script):
    result = run_script(UPDATE, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    git(work, "fetch", "--quiet")
    assert is_ancestor(work, "origin/older", "older")
    assert is_ancestor(work, "origin/main", "main")
    assert git(work, "symbolic-ref", "--short", "HEAD") == "older"


def test_run_from_a_subdirectory_updates_the_branch_checked_out_there(work: Path, run_script):
    """From `sub/`, the CWD matched no worktree root, so `older` - checked out
    right here - looked pinned elsewhere. `git -C <root>` then rebased
    whatever the loop had last checked out, and `older` stayed behind while
    the run reported it up to date."""
    result = run_script(UPDATE, cwd=work / "sub")

    assert result.returncode == 0, result.stdout + result.stderr
    assert is_ancestor(work, "origin/older", "older"), result.stdout
    assert "in its worktree" not in result.stdout
    assert git(work, "symbolic-ref", "--short", "HEAD") == "older"


def test_a_branch_in_another_worktree_is_rebased_in_place(work: Path, run_script, tmp_path: Path):
    git(work, "checkout", "--quiet", "main")
    linked = tmp_path / "wt-older"
    git(work, "worktree", "add", "--quiet", str(linked), "older")

    result = run_script(UPDATE, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "older up to date (in " in result.stdout
    assert is_ancestor(work, "origin/older", "older")
    assert git(linked, "symbolic-ref", "--short", "HEAD") == "older"


def test_a_branch_named_like_a_tag_is_still_rebased(work: Path, run_script):
    """refname:short reads `heads/older` once a tag `older` exists, and
    checking that out detached HEAD instead of switching to the branch."""
    git(work, "checkout", "--quiet", "main")
    git(work, "tag", "older", "older")

    result = run_script(UPDATE, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    # Spelled out: a bare `older` now names the tag, which stays put.
    assert is_ancestor(work, "origin/older", "refs/heads/older")
    assert git(work, "symbolic-ref", "--short", "HEAD") == "main"


def test_the_checked_out_branch_named_like_a_tag_is_rebased(work: Path, run_script):
    """`symbolic-ref --short` reads `heads/older` once a tag `older` exists, so
    the branch checked out right here looked pinned in another worktree: the
    run rebased whatever it had checked out last and reported `older` done."""
    git(work, "tag", "older", "older")

    result = run_script(UPDATE, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert is_ancestor(work, "origin/older", "refs/heads/older"), result.stdout
    assert git(work, "symbolic-ref", "HEAD") == "refs/heads/older"


def test_an_untracked_file_does_not_block(work: Path, run_script):
    """Checkout and rebase leave untracked files alone, so only tracked
    changes count as a dirty tree."""
    (work / "scratch.txt").write_text("in progress\n")

    result = run_script(UPDATE, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert is_ancestor(work, "origin/older", "older")
    assert (work / "scratch.txt").read_text() == "in progress\n"


def test_tracked_changes_block(work: Path, run_script):
    (work / "older.txt").write_text("changed\n")

    result = run_script(UPDATE, cwd=work)

    assert result.returncode == 1
    assert "Working tree is dirty" in result.stdout


def test_limit_must_be_a_count(work: Path, run_script):
    result = run_script(UPDATE, ["--limit=-1"], cwd=work)

    assert result.returncode == 1
    assert "--limit must be a non-negative integer (got: -1)" in result.stdout
