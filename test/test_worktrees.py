"""Tests for the worktree helpers in bin/utils.py.

These build real repositories rather than mocking ``git``: every helper here
exists to answer a question only git can answer ("is this branch pinned to a
worktree?"), so a mock would only prove the mock agrees with itself.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from utils import (
    branch_is_pushed,
    find_main_branch,
    main_worktree,
    worktree_branch_map,
    worktree_for_branch,
    worktree_is_clean,
    worktree_paths,
)


def git(cwd: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo on `main` with one commit, plus an `origin` it can push to."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git(origin, "init", "--bare", "--initial-branch=main", "--quiet")

    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "--initial-branch=main", "--quiet")
    git(work, "config", "user.email", "test@example.com")
    git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("hello\n")
    git(work, "add", "README.md")
    git(work, "commit", "--quiet", "-m", "init")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "--quiet", "--set-upstream", "origin", "main")
    return work


@pytest.fixture
def in_repo(repo: Path):
    """Run the test with the process CWD inside ``repo``.

    The helpers default to the process working directory, exactly as they do
    when a script is invoked from a repo.
    """
    previous = Path.cwd()
    os.chdir(repo)
    try:
        yield repo
    finally:
        os.chdir(previous)


# ---------------------------------------------------------------------------
# worktree_paths / main_worktree
# ---------------------------------------------------------------------------


def test_main_worktree_is_the_first_record(in_repo: Path):
    assert Path(main_worktree()).resolve() == in_repo.resolve()


def test_worktree_paths_lists_main_then_linked(in_repo: Path, tmp_path: Path):
    linked = tmp_path / "wt-feature"
    git(in_repo, "worktree", "add", "--quiet", "-b", "feature", str(linked))

    paths = [Path(p).resolve() for p in worktree_paths()]

    assert paths[0] == in_repo.resolve()
    assert linked.resolve() in paths


def test_worktree_path_with_a_space_survives(in_repo: Path, tmp_path: Path):
    """`awk '{print $2}'` truncated these; taking the whole remainder does not."""
    linked = tmp_path / "my worktree"
    git(in_repo, "worktree", "add", "--quiet", "-b", "spaced", str(linked))

    assert linked.resolve() in [Path(p).resolve() for p in worktree_paths()]


# ---------------------------------------------------------------------------
# worktree_branch_map / worktree_for_branch
# ---------------------------------------------------------------------------


def test_branch_map_includes_the_main_worktree(in_repo: Path):
    """The main worktree's branch is pinned for the same reason a linked one's is."""
    assert Path(worktree_branch_map()["main"]).resolve() == in_repo.resolve()


def test_branch_map_finds_a_linked_worktree(in_repo: Path, tmp_path: Path):
    linked = tmp_path / "wt-feature"
    git(in_repo, "worktree", "add", "--quiet", "-b", "feature", str(linked))

    assert Path(worktree_branch_map()["feature"]).resolve() == linked.resolve()
    assert Path(worktree_for_branch("feature")).resolve() == linked.resolve()


def test_branch_map_skips_detached_worktrees(in_repo: Path, tmp_path: Path):
    """A detached worktree pins no branch, so it must not appear."""
    linked = tmp_path / "wt-detached"
    git(in_repo, "worktree", "add", "--quiet", "--detach", str(linked))

    assert str(linked.resolve()) not in {
        str(Path(p).resolve()) for p in worktree_branch_map().values()
    }


def test_worktree_for_branch_returns_empty_when_unpinned(in_repo: Path):
    git(in_repo, "branch", "loose")

    assert worktree_for_branch("loose") == ""


# ---------------------------------------------------------------------------
# worktree_is_clean
# ---------------------------------------------------------------------------


def test_worktree_is_clean_on_a_fresh_checkout(in_repo: Path):
    assert worktree_is_clean(in_repo) is True


def test_worktree_is_dirty_with_a_modified_file(in_repo: Path):
    (in_repo / "README.md").write_text("changed\n")

    assert worktree_is_clean(in_repo) is False


def test_worktree_is_dirty_with_an_untracked_file(in_repo: Path):
    (in_repo / "scratch.txt").write_text("x\n")

    assert worktree_is_clean(in_repo) is False


def test_worktree_ignores_gitignored_output(in_repo: Path):
    (in_repo / ".gitignore").write_text("build/\n")
    git(in_repo, "add", ".gitignore")
    git(in_repo, "commit", "--quiet", "-m", "ignore build")
    (in_repo / "build").mkdir()
    (in_repo / "build" / "out.js").write_text("x\n")

    assert worktree_is_clean(in_repo) is True


def test_non_worktree_path_is_not_clean(tmp_path: Path):
    """A path that isn't a working tree must not read as clean — a caller would
    otherwise delete a directory it never actually inspected."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    assert worktree_is_clean(plain) is False


# ---------------------------------------------------------------------------
# branch_is_pushed
# ---------------------------------------------------------------------------


def test_branch_is_pushed_when_upstream_matches(in_repo: Path):
    assert branch_is_pushed("main") is True


def test_branch_is_not_pushed_with_a_local_commit(in_repo: Path):
    (in_repo / "new.txt").write_text("x\n")
    git(in_repo, "add", "new.txt")
    git(in_repo, "commit", "--quiet", "-m", "local only")

    assert branch_is_pushed("main") is False


def test_branch_is_not_pushed_without_any_remote_ref(in_repo: Path):
    git(in_repo, "branch", "never-pushed")

    assert branch_is_pushed("never-pushed") is False


def test_branch_is_pushed_falls_back_to_origin_name(in_repo: Path):
    """No configured upstream, but origin/<branch> exists and contains it."""
    git(in_repo, "branch", "sidecar")
    git(in_repo, "push", "--quiet", "origin", "sidecar")
    # push.autoSetupRemote may have set one anyway; the fallback only matters
    # when there is none, so clear it either way.
    git(in_repo, "branch", "--unset-upstream", "sidecar", check=False)

    assert branch_is_pushed("sidecar") is True


# ---------------------------------------------------------------------------
# find_main_branch
# ---------------------------------------------------------------------------


def test_find_main_branch_prefers_main(in_repo: Path):
    git(in_repo, "branch", "master")

    assert find_main_branch(in_repo) == "main"


def test_find_main_branch_falls_back_to_master(in_repo: Path):
    git(in_repo, "branch", "master")
    git(in_repo, "checkout", "--quiet", "master")
    git(in_repo, "branch", "-D", "main")

    assert find_main_branch(in_repo) == "master"


def test_find_main_branch_returns_empty_when_neither_exists(in_repo: Path):
    git(in_repo, "checkout", "--quiet", "-b", "trunk")
    git(in_repo, "branch", "-D", "main")

    assert find_main_branch(in_repo) == ""
