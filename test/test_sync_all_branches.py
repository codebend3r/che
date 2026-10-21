"""Real local-remote regression tests for non-destructive branch/worktree sync."""

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
    "reference-transaction",
)


class Repo(NamedTuple):
    origin: Path
    work: Path
    other: Path
    wip: Path
    shipped: Path
    hook_log: Path


@pytest.fixture
def repo(git_repo: Callable[[str], Path], tmp_path: Path) -> Repo:
    work = git_repo("work")
    for branch in ("behind", "shipped", "mine"):
        git(work, "checkout", "--quiet", "-b", branch, "main")
        commit(work, branch)
        git(work, "push", "--quiet", "--set-upstream", "origin", branch)
    git(work, "checkout", "--quiet", "main")
    git(work, "branch", "--quiet", "-D", "mine")
    other = git_repo("other")
    git(other, "checkout", "--quiet", "behind")
    commit(other, "behind-upstream")
    git(other, "push", "--quiet")
    git(work, "checkout", "--quiet", "behind")
    commit(work, "behind-local")
    git(work, "checkout", "--quiet", "main")
    wip = tmp_path / "wip with spaces"
    git(work, "worktree", "add", "--quiet", "-b", "wip", str(wip), "main")
    commit(wip, "wip")
    git(wip, "push", "--quiet", "--set-upstream", "origin", "wip")
    commit(wip, "wip-local")
    shipped = tmp_path / "shipped"
    git(work, "worktree", "add", "--quiet", str(shipped), "shipped")
    hook_log = tmp_path / "hooks.log"
    for hook in HOOKS:
        path = work / ".git" / "hooks" / hook
        path.write_text(f'#!/bin/sh\necho {hook} >> "{hook_log}"\n')
        path.chmod(0o755)
    return Repo(tmp_path / "origin.git", work, other, wip, shipped, hook_log)


def advance(repo: Repo, branch: str, file: str = "") -> None:
    git(repo.other, "fetch", "--quiet", "origin")
    git(repo.other, "checkout", "--quiet", branch)
    commit(repo.other, file or f"{branch}-remote")
    git(repo.other, "push", "--quiet")


def assert_includes_origin(repo: Repo, branch: str) -> None:
    git(
        repo.work,
        "merge-base",
        "--is-ancestor",
        f"refs/remotes/origin/{branch}",
        f"refs/heads/{branch}",
    )


def worktree_paths(work: Path) -> list[str]:
    return [
        line
        for line in git(work, "worktree", "list", "--porcelain", "-z").split("\0")
        if line.startswith("worktree ")
    ]


def test_sync_runs_no_hooks(repo: Repo, run_script):
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not repo.hook_log.exists()


def test_sync_never_pushes_or_discards_local_commits(repo: Repo, run_script):
    before = git(repo.origin, "show-ref")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo.origin, "show-ref") == before
    assert git(repo.work, "show", "behind:behind-local") == "behind-local"
    assert (repo.wip / "wip-local").read_text() == "wip-local\n"


def test_sync_leaves_every_worktree_in_place(repo: Repo, run_script):
    before = worktree_paths(repo.work)
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert repo.wip.is_dir() and repo.shipped.is_dir()
    assert worktree_paths(repo.work) == before


def test_sync_updates_and_tracks_new_branches(repo: Repo, run_script):
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "mine" in local_branches(repo.work)
    assert git(repo.work, "rev-parse", "--abbrev-ref", "mine@{upstream}") == "origin/mine"
    assert_includes_origin(repo, "behind")


def test_sync_preserves_caller_feature_branch_and_staged_wip(repo: Repo, run_script):
    git(repo.work, "checkout", "--quiet", "behind")
    (repo.work / "scratch.txt").write_text("staged WIP\n")
    git(repo.work, "add", "scratch.txt")
    before = git(repo.work, "diff", "--cached")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "behind"
    assert git(repo.work, "diff", "--cached") == before
    assert_includes_origin(repo, "behind")


def test_locked_dirty_worktree_updates_and_restores_exact_wip(repo: Repo, run_script):
    git(repo.work, "worktree", "lock", "--reason", "supacode owner", str(repo.wip))
    (repo.wip / "older.txt").write_text("unrelated stash\n")
    git(repo.wip, "stash", "push", "-u", "-m", "older unrelated stash")
    older = git(repo.wip, "rev-parse", "refs/stash")
    (repo.wip / "wip").write_text("staged\n")
    git(repo.wip, "add", "wip")
    (repo.wip / "wip").write_text("staged\nunstaged\n")
    (repo.wip / ".build").mkdir()
    (repo.wip / ".build" / "precious.txt").write_text("untracked build\n")
    before = git(repo.wip, "status", "--porcelain")
    index = git(repo.wip, "diff", "--cached")
    diff = git(repo.wip, "diff")
    advance(repo, "wip")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert_includes_origin(repo, "wip")
    assert git(repo.wip, "status", "--porcelain") == before
    assert git(repo.wip, "diff", "--cached") == index
    assert git(repo.wip, "diff") == diff
    assert (repo.wip / ".build" / "precious.txt").read_text() == "untracked build\n"
    assert git(repo.wip, "rev-parse", "refs/stash") == older
    assert "locked supacode owner" in git(repo.work, "worktree", "list", "--porcelain")
    assert "WIP restored: 1 (wip)" in result.stdout


def test_ahead_only_dirty_worktree_needs_no_stash(repo: Repo, run_script):
    scratch = repo.wip / "scratch.txt"
    scratch.write_text("in progress\n")
    before = git(repo.wip, "rev-parse", "HEAD")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert scratch.read_text() == "in progress\n"
    assert git(repo.wip, "rev-parse", "HEAD") == before
    assert git(repo.wip, "stash", "list") == ""


def test_nested_checkout_is_excluded_from_stash_but_sibling_wip_is_restored(repo: Repo, run_script):
    nested = repo.work / ".worktrees" / "nested"
    git(repo.work, "worktree", "add", "--quiet", "-b", "nested", str(nested), "main")
    (nested / "nested-WIP.txt").write_text("nested unfinished work\n")
    sibling = repo.work / ".worktrees" / "sibling.txt"
    sibling.write_text("parent unfinished work\n")
    advance(repo, "main")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert_includes_origin(repo, "main")
    assert sibling.read_text() == "parent unfinished work\n"
    assert (nested / "nested-WIP.txt").read_text() == "nested unfinished work\n"
    assert git(nested, "symbolic-ref", "--short", "HEAD") == "nested"
    assert git(repo.work, "stash", "list") == ""


def test_sync_from_linked_worktree_preserves_both_checkouts(repo: Repo, run_script):
    git(repo.work, "checkout", "--quiet", "behind")
    advance(repo, "wip")
    result = run_script(SYNC, cwd=repo.wip)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "behind"
    assert git(repo.wip, "symbolic-ref", "--short", "HEAD") == "wip"
    assert_includes_origin(repo, "wip")


def test_detached_caller_is_preserved(repo: Repo, run_script):
    git(repo.work, "checkout", "--detach", "--quiet")
    before = git(repo.work, "rev-parse", "HEAD")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo.work, "rev-parse", "HEAD") == before
    assert git(repo.work, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert_includes_origin(repo, "behind")


def test_fallback_origin_for_untracked_branch_and_tag_collision(repo: Repo, run_script):
    git(repo.work, "config", "--unset", "branch.behind.remote")
    git(repo.work, "config", "--unset", "branch.behind.merge")
    git(repo.work, "tag", "behind")
    git(repo.work, "branch", "local-only")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert_includes_origin(repo, "behind")
    assert "Local only: 1 (local-only)" in result.stdout


def test_gone_upstream_is_reported_and_kept(repo: Repo, run_script):
    git(repo.other, "push", "--quiet", "origin", "--delete", "shipped")
    before = git(repo.shipped, "rev-parse", "HEAD")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Upstream gone: 1 (shipped)" in result.stdout
    assert "Blocked: 0" in result.stdout
    assert git(repo.shipped, "rev-parse", "HEAD") == before
    assert "shipped" in local_branches(repo.work)
    assert_includes_origin(repo, "behind")
    assert "mine" in local_branches(repo.work)


def make_conflict(repo: Repo) -> str:
    (repo.wip / "wip").write_text("local conflicting commit\n")
    git(repo.wip, "add", "wip")
    git(repo.wip, "commit", "--quiet", "-m", "local conflicting commit")
    before = git(repo.wip, "rev-parse", "HEAD")
    git(repo.other, "fetch", "--quiet", "origin")
    git(repo.other, "checkout", "--quiet", "wip")
    (repo.other / "wip").write_text("remote conflicting commit\n")
    git(repo.other, "add", "wip")
    git(repo.other, "commit", "--quiet", "-m", "remote conflicting commit")
    git(repo.other, "push", "--quiet")
    return before


def test_rebase_conflict_aborts_restores_wip_and_continues(repo: Repo, run_script):
    before = make_conflict(repo)
    git(repo.work, "branch", "--track", "z-after-conflict", "refs/remotes/origin/behind")
    (repo.wip / "unfinished.txt").write_text("unfinished WIP\n")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 1, result.stdout + result.stderr
    assert git(repo.wip, "rev-parse", "HEAD") == before
    assert (repo.wip / "unfinished.txt").read_text() == "unfinished WIP\n"
    assert not Path(git(repo.wip, "rev-parse", "--git-path", "rebase-merge")).exists()
    assert git(repo.wip, "stash", "list") == ""
    assert "wip: rebase failed" in result.stdout
    git(repo.work, "merge-base", "--is-ancestor", "refs/remotes/origin/behind", "z-after-conflict")
    assert "Updated: z-after-conflict" in result.stdout
    assert "mine" in local_branches(repo.work)
    assert_includes_origin(repo, "behind")


def test_stash_restore_conflict_keeps_recovery_stash(repo: Repo, run_script):
    (repo.wip / "wip").write_text("uncommitted local WIP\n")
    git(repo.other, "fetch", "--quiet", "origin")
    git(repo.other, "checkout", "--quiet", "wip")
    (repo.other / "wip").write_text("remote modification\n")
    git(repo.other, "add", "wip")
    git(repo.other, "commit", "--quiet", "-m", "remote modification")
    git(repo.other, "push", "--quiet")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 1, result.stdout + result.stderr
    assert_includes_origin(repo, "wip")
    assert git(repo.wip, "show", "stash:wip") == "uncommitted local WIP"
    assert "recovery stash retained" in result.stdout
    assert git(repo.wip, "status", "--porcelain")
    assert "mine" in local_branches(repo.work)


def test_existing_rebase_is_left_untouched(repo: Repo, run_script):
    import subprocess

    make_conflict(repo)
    git(repo.wip, "fetch", "--quiet", "origin")
    rebase = subprocess.run(
        ["git", "rebase", "origin/wip"], cwd=repo.wip, capture_output=True, text=True
    )
    assert rebase.returncode != 0
    before = git(repo.wip, "status", "--porcelain")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "wip: operation in progress" in result.stdout
    assert git(repo.wip, "status", "--porcelain") == before
    assert Path(git(repo.wip, "rev-parse", "--git-path", "rebase-merge")).exists()
    assert_includes_origin(repo, "behind")


def test_dirty_submodule_is_preserved_and_other_branches_continue(repo: Repo, git_repo, run_script):
    module = git_repo("module")
    git(
        repo.work,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(module),
        "deps/module",
    )
    git(repo.work, "commit", "--quiet", "-m", "add local submodule")
    before = git(repo.work, "rev-parse", "HEAD")
    nested = repo.work / "deps" / "module"
    (nested / "README.md").write_text("uncommitted submodule work\n")
    advance(repo, "main")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "dirty/unreadable submodule" in result.stdout
    assert git(repo.work, "rev-parse", "HEAD") == before
    assert (nested / "README.md").read_text() == "uncommitted submodule work\n"
    assert git(repo.work, "stash", "list") == ""
    assert_includes_origin(repo, "behind")
    assert "mine" in local_branches(repo.work)


def test_author_filter_applies_to_new_tracking_branches(repo: Repo, run_script):
    result = run_script(SYNC, ["--author=somebody-else@example.com"], cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "mine" not in local_branches(repo.work)
    assert_includes_origin(repo, "behind")


def test_main_local_commits_are_never_hard_reset(repo: Repo, run_script):
    commit(repo.work, "main-local")
    advance(repo, "main")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo.work / "main-local").read_text() == "main-local\n"
    assert_includes_origin(repo, "main")


def test_explicit_flag_beats_inherited_dry_run_and_legacy_flags_work(repo: Repo, run_script):
    result = run_script(
        SYNC,
        ["--dry-run=false", "--no-push", "--keep-locked"],
        env={"DRY_RUN": "true"},
        cwd=repo.work,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert_includes_origin(repo, "behind")


def test_dry_run_does_not_fetch_stash_or_change_any_ref_or_checkout(repo: Repo, run_script):
    git(repo.work, "checkout", "--quiet", "behind")
    (repo.work / "scratch.txt").write_text("WIP\n")
    before = git(repo.work, "show-ref")
    trees = git(repo.work, "worktree", "list", "--porcelain", "-z")
    result = run_script(SYNC, ["--dry-run"], cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo.work, "show-ref") == before
    assert git(repo.work, "worktree", "list", "--porcelain", "-z") == trees
    assert git(repo.work, "symbolic-ref", "--short", "HEAD") == "behind"
    assert (repo.work / "scratch.txt").read_text() == "WIP\n"
    assert git(repo.work, "stash", "list") == ""
    assert "Cached remote refs only; no fetch" in result.stdout


def test_the_sync_fetches_once(repo: Repo, run_script):
    trace_path = repo.work.parent / "trace"
    result = run_script(SYNC, cwd=repo.work, env={"GIT_TRACE": str(trace_path)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("Fetching") == 1
    assert trace_path.read_text().count("built-in: git upload-pack") == 1


def test_fetch_failure_changes_no_local_branch_or_worktree(repo: Repo, run_script):
    git(repo.work, "remote", "set-url", "origin", str(repo.work.parent / "missing-origin"))
    before = git(repo.work, "show-ref")
    trees = worktree_paths(repo.work)
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode != 0
    assert git(repo.work, "show-ref") == before
    assert worktree_paths(repo.work) == trees


@pytest.mark.parametrize("value", ["0", "-1", "bad"])
def test_invalid_limit_fails_before_fetch(repo: Repo, run_script, value: str):
    before = git(repo.work, "show-ref")
    result = run_script(SYNC, [f"--limit={value}"], cwd=repo.work)
    assert result.returncode == 1
    assert git(repo.work, "show-ref") == before


def squash_parent_and_force_push_child(repo: Repo, child_path: Path | None = None) -> None:
    """Rebuild a squash-merge seen from a stale clone, as GitHub plus another machine leave it.

    ``parent`` lands on main as one squash commit and its remote branch is
    deleted; ``child``, cut from ``parent``, is rebased onto the new main and
    force-pushed elsewhere. The local ``child`` still carries the pre-squash
    commits, which conflict on replay although main already holds their content.
    """
    git(repo.work, "checkout", "--quiet", "-b", "parent", "main")
    (repo.work / "parent").write_text("one\n")
    git(repo.work, "add", "parent")
    git(repo.work, "commit", "--quiet", "-m", "parent one")
    (repo.work / "parent").write_text("one\ntwo\n")
    git(repo.work, "commit", "--quiet", "-am", "parent two")
    git(repo.work, "push", "--quiet", "--set-upstream", "origin", "parent")
    if child_path is None:
        git(repo.work, "checkout", "--quiet", "-b", "child")
        commit(repo.work, "child")
        git(repo.work, "push", "--quiet", "--set-upstream", "origin", "child")
        git(repo.work, "checkout", "--quiet", "main")
    else:
        git(repo.work, "checkout", "--quiet", "main")
        git(repo.work, "worktree", "add", "--quiet", "-b", "child", str(child_path), "parent")
        commit(child_path, "child")
        git(child_path, "push", "--quiet", "--set-upstream", "origin", "child")
    git(repo.other, "fetch", "--quiet", "origin")
    git(repo.other, "checkout", "--quiet", "main")
    git(repo.other, "pull", "--quiet", "--ff-only")
    git(repo.other, "merge", "--quiet", "--squash", "origin/parent")
    git(repo.other, "commit", "--quiet", "-m", "parent (#1)")
    git(repo.other, "push", "--quiet", "origin", "main", ":parent")
    git(repo.other, "checkout", "--quiet", "-B", "child", "main")
    git(repo.other, "cherry-pick", "origin/child")
    git(repo.other, "push", "--quiet", "--force", "origin", "child")


def test_squash_merged_parent_is_deleted_and_stale_child_reset(repo: Repo, run_script):
    squash_parent_and_force_push_child(repo)
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "parent" not in local_branches(repo.work)
    assert git(repo.work, "rev-parse", "child") == git(repo.work, "rev-parse", "origin/child")
    assert "Reset to upstream: 1 (child)" in result.stdout
    assert "Deleted (merged): 1 (parent)" in result.stdout


def test_stale_child_in_worktree_resets_in_place_and_keeps_wip(
    repo: Repo, run_script, tmp_path: Path
):
    child = tmp_path / "child"
    squash_parent_and_force_push_child(repo, child)
    (child / "child").write_text("child\nuncommitted\n")
    (child / "notes.txt").write_text("untracked\n")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(child, "symbolic-ref", "--short", "HEAD") == "child"
    assert git(child, "rev-parse", "HEAD") == git(repo.work, "rev-parse", "origin/child")
    assert (child / "child").read_text() == "child\nuncommitted\n"
    assert (child / "notes.txt").read_text() == "untracked\n"
    assert git(child, "stash", "list") == ""


def test_child_with_unique_local_commit_is_never_reset(repo: Repo, run_script):
    squash_parent_and_force_push_child(repo)
    git(repo.work, "checkout", "--quiet", "child")
    commit(repo.work, "child-local")
    git(repo.work, "checkout", "--quiet", "main")
    before = git(repo.work, "rev-parse", "child")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "child: rebase failed" in result.stdout
    assert git(repo.work, "rev-parse", "child") == before
    assert "parent" not in local_branches(repo.work)


def test_dry_run_previews_reset_and_delete_without_changing_refs(repo: Repo, run_script):
    squash_parent_and_force_push_child(repo)
    git(repo.work, "fetch", "--quiet", "--prune", "origin")
    before = git(repo.work, "show-ref")
    result = run_script(SYNC, ["--dry-run"], cwd=repo.work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo.work, "show-ref") == before
    assert "Would reset child to refs/remotes/origin/child" in result.stdout
    assert "Would delete parent: upstream gone, work already in main" in result.stdout


def test_gone_merged_branch_checked_out_in_worktree_is_kept(repo: Repo, run_script, tmp_path: Path):
    squash_parent_and_force_push_child(repo)
    parent = tmp_path / "parent"
    git(repo.work, "worktree", "add", "--quiet", str(parent), "parent")
    result = run_script(SYNC, cwd=repo.work)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "parent" in local_branches(repo.work)
    assert f"merged into main, but checked out in {parent}" in result.stdout
    assert git(parent, "symbolic-ref", "--short", "HEAD") == "parent"
