"""End-to-end tests for ``bin/git/sync-all-branches.py``.

The sync only deletes merged branches, rebases tracked ones and checks out new
ones. None of that is the user committing or pushing, so no repo hook (a
lefthook or husky pre-commit, pre-push, post-checkout) may run, nothing may be
pushed, and every worktree stays where it is. The repo below gives every step
something to do, with a hook of every kind that logs when it fires.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest
from conftest import commit, git, local_branches

SYNC = "git/sync-all-branches.py"

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


class Repo(NamedTuple):
    origin: Path
    work: Path
    wip: Path
    shipped: Path
    hook_log: Path


@pytest.fixture
def repo(git_repo: Callable[[str], Path], tmp_path: Path) -> Repo:
    """A clone, its origin, and two linked worktrees.

    ``work`` is on main and has, by the time the sync runs:
      - ``stale``: pushed, then deleted on origin
      - ``behind``: origin moved on, and a local commit must be replayed
      - ``wip``: checked out in a linked worktree with an unpushed commit
      - ``shipped``: checked out in a clean linked worktree, fully pushed
      - ``mine``: on origin only, authored by ``EMAIL``
    """
    work = git_repo("work")
    origin = tmp_path / "origin.git"

    for branch in ("stale", "behind", "shipped", "mine"):
        git(work, "checkout", "--quiet", "-b", branch, "main")
        commit(work, branch)
        git(work, "push", "--quiet", "--set-upstream", "origin", branch)
    git(work, "checkout", "--quiet", "main")
    git(work, "branch", "--quiet", "-D", "mine")

    other = git_repo("other")
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


def test_sync_runs_no_hooks(repo: Repo, run_script):
    result = run_script(SYNC, cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    fired = repo.hook_log.read_text().split() if repo.hook_log.exists() else []
    assert fired == []


def test_sync_never_pushes(repo: Repo, run_script):
    result = run_script(SYNC, cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo.origin, "branch", "--list", "wip") == ""


def test_sync_leaves_every_worktree_in_place(repo: Repo, run_script):
    before = worktree_paths(repo.work)

    result = run_script(SYNC, cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert repo.wip.is_dir()
    assert repo.shipped.is_dir()
    assert worktree_paths(repo.work) == before


def test_sync_still_tidies_every_branch(repo: Repo, run_script):
    work = repo.work

    result = run_script(SYNC, cwd=work)

    assert result.returncode == 0, result.stdout + result.stderr
    local = local_branches(work)
    assert "stale" not in local
    assert "mine" in local
    git(work, "merge-base", "--is-ancestor", "origin/behind", "behind")


def test_sync_ends_parked_on_main(repo: Repo, run_script):
    """checkout-my-branches runs last; it must create `mine` without switching
    to it, or the sync would end wherever the newest branch happened to be."""
    result = run_script(SYNC, cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "main"
    assert git(repo.work, "rev-parse", "--abbrev-ref", "mine@{upstream}") == "origin/mine"


def test_sync_parks_a_main_clone_left_on_another_branch(repo: Repo, run_script):
    git(repo.work, "checkout", "--quiet", "behind")

    result = run_script(SYNC, cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Switching main worktree to 🌿 main (from behind)" in result.stdout
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "main"


def test_separators_stay_in_order_when_piped(repo: Repo, run_script):
    """stdout is a pipe here. Each child writes to it directly, so a blank line
    the parent printed without flushing surfaced after the children instead
    of before each one."""
    result = run_script(SYNC, cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    for title in (
        "🧹  clean-stale-branches",
        "⬇️   update-local-branches",
        "🌿  checkout-my-branches",
    ):
        index = lines.index(title)
        # A blank line, then the banner's top rule, then its title.
        assert lines[index - 2] == "", f"no separator before {title!r}:\n{result.stdout}"
    assert lines[-2] != "", "a separator leaked to the end of the run"


def test_an_explicit_flag_beats_an_inherited_dry_run(repo: Repo, run_script):
    """Dry-run reaches the children as --dry-run=..., which outranks whatever
    DRY_RUN they inherit."""
    result = run_script(SYNC, ["--dry-run=false"], env={"DRY_RUN": "true"}, cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "stale" not in local_branches(repo.work)


def test_dry_run_changes_no_branch(repo: Repo, run_script):
    git(repo.work, "checkout", "--quiet", "behind")
    before = git(repo.work, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")

    result = run_script(SYNC, ["--dry-run"], cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo.work, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads") == (
        before
    )
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "behind"


def test_a_dirty_worktree_is_skipped_not_fatal(repo: Repo, run_script):
    scratch = repo.shipped / "scratch.txt"
    scratch.write_text("in progress\n")

    result = run_script(SYNC, cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert scratch.read_text() == "in progress\n"
    assert "mine" in local_branches(repo.work)


def test_a_worktree_nested_in_the_clone_does_not_stop_the_sync(repo: Repo, run_script):
    """It shows up as untracked. Parking ignored it, then update-local-branches
    counted it as a dirty tree and the sync aborted at that step."""
    git(repo.work, "worktree", "add", "--quiet", "-b", "nested", ".worktrees/nested", "main")

    result = run_script(SYNC, cwd=repo.work)

    assert result.returncode == 0, result.stdout + result.stderr
    git(repo.work, "merge-base", "--is-ancestor", "origin/behind", "behind")


def test_the_sync_fetches_once(repo: Repo, run_script):
    """Each step fetched for itself, and update-local-branches pulled once per
    branch on top: the steps now inherit the sync's one fetch."""
    result = run_script(SYNC, cwd=repo.work, env={"GIT_TRACE": str(repo.work.parent / "trace")})

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("Fetching") == 1
    # Every fetch or pull from origin serves itself through one upload-pack.
    trace = (repo.work.parent / "trace").read_text()
    assert trace.count("built-in: git upload-pack") == 1, trace
