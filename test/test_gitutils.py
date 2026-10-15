"""Tests for bin/gitutils.py.

The repository helpers build real repositories rather than mocking ``git``:
every one exists to answer a question only git can answer ("is this branch
pinned to a worktree?"), so a mock would only prove the mock agrees with itself.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest import mock

import pytest
from conftest import git
from gitutils import (
    Worktree,
    current_branch,
    fetch_remotes,
    find_main_branch,
    for_each_ref,
    has_tracked_changes,
    local_branches,
    park_main_worktree,
    skip_git_hooks,
    worktree_branch_map,
    worktree_is_clean,
    worktrees,
)


@pytest.fixture
def isolated_env() -> Iterator[None]:
    """os.environ restored afterwards: the helpers under test write to it.

    Starts with no ``GIT_CONFIG_*`` and no fetch marker, so an outer run (the
    pre-push hook, a sync) cannot leak into what is asserted.
    """
    with mock.patch.dict(os.environ):
        for key in [k for k in os.environ if k.startswith("GIT_CONFIG_")]:
            del os.environ[key]
        os.environ.pop("CHE_REMOTES_FETCHED", None)
        yield


# ---------------------------------------------------------------------------
# skip_git_hooks
# ---------------------------------------------------------------------------


def test_skip_git_hooks_points_hooks_path_at_devnull(isolated_env):
    skip_git_hooks()

    assert os.environ["GIT_CONFIG_COUNT"] == "1"
    assert os.environ["GIT_CONFIG_KEY_0"] == "core.hooksPath"
    assert os.environ["GIT_CONFIG_VALUE_0"] == os.devnull


def test_skip_git_hooks_appends_after_existing_entries(isolated_env):
    os.environ["GIT_CONFIG_COUNT"] = "1"
    os.environ["GIT_CONFIG_KEY_0"] = "user.name"
    os.environ["GIT_CONFIG_VALUE_0"] = "Someone"

    skip_git_hooks()

    assert os.environ["GIT_CONFIG_COUNT"] == "2"
    assert os.environ["GIT_CONFIG_KEY_0"] == "user.name"
    assert os.environ["GIT_CONFIG_KEY_1"] == "core.hooksPath"


def test_skip_git_hooks_twice_adds_one_entry(isolated_env):
    skip_git_hooks()
    skip_git_hooks()

    assert os.environ["GIT_CONFIG_COUNT"] == "1"


@pytest.fixture
def in_repo(
    git_repo: Callable[[str], Path], monkeypatch: pytest.MonkeyPatch, isolated_env: None
) -> Path:
    """A repo on `main` with one commit pushed to its `origin`, as the CWD.

    The helpers default to the process working directory, exactly as they do
    when a script is invoked from a repo.
    """
    repo = git_repo("work")
    monkeypatch.chdir(repo)
    return repo


def resolved(found: list[Worktree]) -> list[tuple[Path, str]]:
    return [(Path(w.path).resolve(), w.branch) for w in found]


# ---------------------------------------------------------------------------
# worktrees
# ---------------------------------------------------------------------------


def test_worktrees_lists_main_first_then_linked(in_repo: Path, tmp_path: Path):
    linked = tmp_path / "wt-feature"
    git(in_repo, "worktree", "add", "--quiet", "-b", "feature", str(linked))

    assert resolved(worktrees()) == [(in_repo.resolve(), "main"), (linked.resolve(), "feature")]


def test_worktrees_gives_a_detached_worktree_no_branch(in_repo: Path, tmp_path: Path):
    linked = tmp_path / "wt-detached"
    git(in_repo, "worktree", "add", "--quiet", "--detach", str(linked))

    assert resolved(worktrees())[1] == (linked.resolve(), "")


def test_worktree_path_with_a_space_survives(in_repo: Path, tmp_path: Path):
    """`awk '{print $2}'` truncated these; taking the whole remainder does not."""
    linked = tmp_path / "my worktree"
    git(in_repo, "worktree", "add", "--quiet", "-b", "spaced", str(linked))

    assert (linked.resolve(), "spaced") in resolved(worktrees())


def test_worktrees_answers_for_another_cwd(in_repo: Path, tmp_path: Path):
    linked = tmp_path / "wt-feature"
    git(in_repo, "worktree", "add", "--quiet", "-b", "feature", str(linked))

    # Asked from the linked worktree, the main worktree still comes first.
    assert resolved(worktrees(linked))[0] == (in_repo.resolve(), "main")


# ---------------------------------------------------------------------------
# worktree_branch_map
# ---------------------------------------------------------------------------


def test_branch_map_includes_the_main_worktree(in_repo: Path):
    """The main worktree's branch is pinned for the same reason a linked one's is."""
    assert Path(worktree_branch_map()["main"]).resolve() == in_repo.resolve()


def test_branch_map_finds_a_linked_worktree(in_repo: Path, tmp_path: Path):
    linked = tmp_path / "wt-feature"
    git(in_repo, "worktree", "add", "--quiet", "-b", "feature", str(linked))

    assert Path(worktree_branch_map()["feature"]).resolve() == linked.resolve()


def test_branch_map_skips_detached_worktrees(in_repo: Path, tmp_path: Path):
    """A detached worktree pins no branch, so it must not appear."""
    linked = tmp_path / "wt-detached"
    git(in_repo, "worktree", "add", "--quiet", "--detach", str(linked))

    assert str(linked.resolve()) not in {
        str(Path(p).resolve()) for p in worktree_branch_map().values()
    }


def test_branch_map_omits_an_unpinned_branch(in_repo: Path):
    git(in_repo, "branch", "loose")

    assert "loose" not in worktree_branch_map()


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


# ---------------------------------------------------------------------------
# current_branch
# ---------------------------------------------------------------------------


def test_current_branch_names_the_checked_out_branch(in_repo: Path):
    git(in_repo, "checkout", "--quiet", "-b", "feature/x")

    assert current_branch() == "feature/x"


def test_current_branch_is_empty_when_detached(in_repo: Path):
    git(in_repo, "checkout", "--quiet", "--detach")

    assert current_branch() == ""


def test_current_branch_answers_for_the_worktree_at_cwd(in_repo: Path, tmp_path: Path):
    linked = tmp_path / "wt-feature"
    git(in_repo, "worktree", "add", "--quiet", "-b", "feature", str(linked))

    assert current_branch(linked) == "feature"
    assert current_branch() == "main"


# ---------------------------------------------------------------------------
# for_each_ref
# ---------------------------------------------------------------------------


def test_for_each_ref_returns_one_field_list_per_ref(in_repo: Path):
    git(in_repo, "branch", "loose")

    assert for_each_ref("refs/heads/", "refname:short", "upstream:short") == [
        ["loose", ""],
        ["main", "origin/main"],
    ]


def test_for_each_ref_keeps_a_pipe_inside_one_field(in_repo: Path):
    """The shell's `|` separator split this branch into two records."""
    git(in_repo, "branch", "a|b")

    assert ["a|b", ""] in for_each_ref("refs/heads/", "refname:short", "upstream")


def test_for_each_ref_sorts(in_repo: Path):
    git(in_repo, "branch", "zz")
    git(in_repo, "branch", "aa")

    names = [name for (name,) in for_each_ref("refs/heads/", "refname:short", sort="-refname")]
    assert names == ["zz", "main", "aa"]


def test_for_each_ref_with_no_match_is_empty(in_repo: Path):
    assert for_each_ref("refs/tags/", "refname") == []


# ---------------------------------------------------------------------------
# local_branches
# ---------------------------------------------------------------------------


def test_local_branches_leads_with_the_name(in_repo: Path):
    git(in_repo, "branch", "feat/nested")

    assert local_branches("upstream:short") == [["feat/nested", ""], ["main", "origin/main"]]


def test_local_branches_names_a_branch_that_shares_a_tags_name(in_repo: Path):
    """refname:short reads `heads/main` here, a name `git branch -D` rejects."""
    git(in_repo, "tag", "main")

    assert local_branches() == [["main"]]


# ---------------------------------------------------------------------------
# has_tracked_changes
# ---------------------------------------------------------------------------


def test_has_tracked_changes_sees_a_modified_file(in_repo: Path):
    (in_repo / "README.md").write_text("changed\n")

    assert has_tracked_changes() is True


def test_has_tracked_changes_ignores_untracked_files_and_nested_worktrees(in_repo: Path):
    (in_repo / "scratch.txt").write_text("x\n")
    git(in_repo, "worktree", "add", "--quiet", "-b", "nested", ".worktrees/nested")

    assert has_tracked_changes() is False


# ---------------------------------------------------------------------------
# fetch_remotes
# ---------------------------------------------------------------------------


def test_fetch_remotes_fetches_once_per_run(in_repo: Path, capsys):
    fetch_remotes()
    fetch_remotes()

    assert capsys.readouterr().out.count("Fetching") == 1
    assert os.environ["CHE_REMOTES_FETCHED"] == "1"


def test_fetch_remotes_prunes_a_deleted_remote_branch(in_repo: Path):
    git(in_repo, "push", "--quiet", "origin", "main:gone")
    git(in_repo, "fetch", "--quiet")
    git(in_repo, "push", "--quiet", "origin", "--delete", "gone")

    fetch_remotes()

    assert for_each_ref("refs/remotes/origin/gone", "refname") == []


# ---------------------------------------------------------------------------
# park_main_worktree
# ---------------------------------------------------------------------------


def test_park_on_main_already_changes_nothing(in_repo: Path, capsys):
    assert park_main_worktree("sync", dry_run=False).resolve() == in_repo.resolve()

    assert "already on 🌿 main" in capsys.readouterr().out
    assert current_branch(in_repo) == "main"


def test_park_switches_the_main_worktree_to_main(in_repo: Path):
    git(in_repo, "checkout", "--quiet", "-b", "feature")

    park_main_worktree("sync", dry_run=False)

    assert current_branch(in_repo) == "main"


def test_park_dry_run_only_reports_the_switch(in_repo: Path, capsys):
    git(in_repo, "checkout", "--quiet", "-b", "feature")

    park_main_worktree("sync", dry_run=True)

    assert "Would switch main worktree to 🌿 main" in capsys.readouterr().out
    assert current_branch(in_repo) == "feature"


def test_park_from_a_linked_worktree_parks_the_main_one(
    in_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    git(in_repo, "checkout", "--quiet", "-b", "feature")
    linked = tmp_path / "wt-other"
    git(in_repo, "worktree", "add", "--quiet", "-b", "other", str(linked))
    monkeypatch.chdir(linked)

    assert park_main_worktree("prune", dry_run=False).resolve() == in_repo.resolve()

    assert current_branch(in_repo) == "main"
    assert current_branch(linked) == "other"


def test_park_refuses_over_tracked_changes(in_repo: Path, capsys):
    git(in_repo, "checkout", "--quiet", "-b", "feature")
    (in_repo / "README.md").write_text("changed\n")

    with pytest.raises(SystemExit) as exited:
        park_main_worktree("prune", dry_run=False)

    assert exited.value.code == 1
    assert "commit or stash before you prune" in capsys.readouterr().out
    assert current_branch(in_repo) == "feature"


def test_park_ignores_untracked_files(in_repo: Path):
    """Linked worktrees nested in the main one show up as untracked."""
    git(in_repo, "checkout", "--quiet", "-b", "feature")
    (in_repo / "scratch.txt").write_text("x\n")

    park_main_worktree("sync", dry_run=False)

    assert current_branch(in_repo) == "main"


def test_park_refuses_without_main_or_master(in_repo: Path, capsys):
    git(in_repo, "checkout", "--quiet", "-b", "trunk")
    git(in_repo, "branch", "-D", "main")

    with pytest.raises(SystemExit) as exited:
        park_main_worktree("sync", dry_run=False)

    assert exited.value.code == 1
    assert "refusing to sync" in capsys.readouterr().out


@pytest.mark.parametrize("where", ["outside", "git-dir"])
def test_park_refuses_outside_a_working_tree(
    git_repo: Callable[[str], Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, where
):
    """Inside .git, rev-parse exits 0 but answers "false"."""
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain if where == "outside" else git_repo("work") / ".git")

    with pytest.raises(SystemExit) as exited:
        park_main_worktree("sync", dry_run=False)

    assert exited.value.code == 1
    assert "Not inside a git working tree" in capsys.readouterr().out
