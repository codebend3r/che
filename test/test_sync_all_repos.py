"""sync-all-repos: discovery, the per-repo cache, and skips, against real local remotes."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import commit, git, load_script, summary

SCRIPT = "git/sync-all-repos.py"


@pytest.fixture
def sweep(tmp_path: Path, run_script: Callable) -> Callable:
    """Run sync-all-repos over ``tmp_path/repos`` with its cache in ``tmp_path/cache``."""

    def _run(*args: str, env: dict[str, str] | None = None):
        return run_script(
            SCRIPT,
            [f"--root={tmp_path / 'repos'}", f"--cache-dir={tmp_path / 'cache'}", *args],
            env=env,
        )

    return _run


@pytest.fixture
def repos(git_repo: Callable[[str], Path]) -> tuple[Path, Path]:
    return git_repo("repos/alpha"), git_repo("repos/beta")


def test_first_run_syncs_and_the_second_reads_from_cache(sweep, repos, tmp_path):
    first = sweep()
    assert first.returncode == 0, first.stdout + first.stderr
    assert sorted(summary(first.stdout)["Synced"]) == ["alpha", "beta"]
    assert len(list((tmp_path / "cache").glob("*.json"))) == 2

    second = sweep()
    assert second.returncode == 0, second.stdout + second.stderr
    rows = summary(second.stdout)
    assert sorted(rows["From cache"]) == ["alpha", "beta"]
    assert "Synced" not in rows


def test_a_push_elsewhere_resyncs_the_repos_on_that_remote(sweep, repos, git_repo):
    alpha, _ = repos
    assert sweep().returncode == 0
    other = git_repo("elsewhere")
    commit(other, "remote-change")
    git(other, "push", "--quiet")

    result = sweep()
    assert result.returncode == 0, result.stdout + result.stderr
    rows = summary(result.stdout)
    # Both clones share one origin, so both see the push.
    assert sorted(rows["Synced"]) == ["alpha", "beta"]
    assert (alpha / "remote-change").exists()


def test_a_local_commit_resyncs_only_that_repo(sweep, repos):
    alpha, _ = repos
    assert sweep().returncode == 0
    commit(alpha, "local-change")

    rows = summary(sweep().stdout)
    assert rows["Synced"] == ["alpha"]
    assert rows["From cache"] == ["beta"]


def test_dirty_work_is_synced_not_skipped(sweep, repos):
    alpha, _ = repos
    (alpha / "scratch.txt").write_text("wip\n")
    result = sweep()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "alpha" in summary(result.stdout)["Synced"]
    assert (alpha / "scratch.txt").read_text() == "wip\n"


def test_passthrough_flags_are_part_of_the_cache_key(sweep, repos):
    assert sweep().returncode == 0
    rows = summary(sweep("--limit=5").stdout)
    assert sorted(rows["Synced"]) == ["alpha", "beta"]


def test_force_ignores_the_cache(sweep, repos):
    assert sweep().returncode == 0
    rows = summary(sweep("--force").stdout)
    assert sorted(rows["Synced"]) == ["alpha", "beta"]


def test_dry_run_writes_no_cache(sweep, repos, tmp_path):
    result = sweep(env={"DRY_RUN": "true"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(summary(result.stdout)["Would sync"]) == ["alpha", "beta"]
    assert not (tmp_path / "cache").exists()


def test_offline_keeps_its_own_fingerprint(sweep, repos):
    assert sweep().returncode == 0
    rows = summary(sweep("--offline").stdout)
    assert sorted(rows["From cache"]) == ["alpha", "beta"]


def test_no_origin_and_unreachable_are_skips(sweep, repos, git_repo, tmp_path):
    alpha, beta = repos
    git(alpha, "remote", "remove", "origin")
    git(beta, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    result = sweep()
    assert result.returncode == 2, result.stdout + result.stderr
    rows = summary(result.stdout)
    assert rows["No origin"] == ["alpha: no origin remote to sync against"]
    assert rows["Unreachable"][0].startswith("beta:")


def test_a_failed_sync_exits_one_and_is_not_cached(sweep, repos, tmp_path):
    alpha, _ = repos
    # origin still answers the probe, but `git fetch --all` fails on this one.
    git(alpha, "remote", "add", "broken", str(tmp_path / "missing.git"))
    result = sweep()
    assert result.returncode == 1, result.stdout + result.stderr
    assert summary(result.stdout)["Failed"][0].startswith("alpha:")
    entries = [json.loads(p.read_text())["repo"] for p in (tmp_path / "cache").glob("*.json")]
    assert entries == [str(repos[1])]


def test_clear_cache(sweep, repos, tmp_path):
    assert sweep().returncode == 0
    assert sweep("--clear-cache", env={"DRY_RUN": "true"}).returncode == 0
    assert (tmp_path / "cache").exists()
    assert sweep("--clear-cache").returncode == 0
    assert not (tmp_path / "cache").exists()


def test_explicit_repos_limit_the_sweep(run_script, repos, tmp_path):
    alpha, _ = repos
    result = run_script(SCRIPT, [f"--cache-dir={tmp_path / 'cache'}", str(alpha / "subdir")])
    assert result.returncode == 1  # no such directory
    (alpha / "subdir").mkdir()
    result = run_script(SCRIPT, [f"--cache-dir={tmp_path / 'cache'}", str(alpha / "subdir")])
    assert result.returncode == 0, result.stdout + result.stderr
    assert summary(result.stdout)["Synced"] == ["alpha"]


# -- pure parts --------------------------------------------------------------

mod = load_script(SCRIPT)


def test_discover_skips_worktrees_nested_repos_pruned_dirs_and_depth(tmp_path):
    root = tmp_path / "root"
    for path in (
        "a/.git",
        "a/inner/.git",
        "group/b/.git",
        "group/deep/c/.git",
        "node_modules/d/.git",
    ):
        (root / path).mkdir(parents=True)
    (root / "wt").mkdir()
    (root / "wt" / ".git").write_text("gitdir: elsewhere\n")

    assert mod.discover([root], depth=2) == [root / "a", root / "group" / "b"]
    assert root / "group" / "deep" / "c" in mod.discover([root], depth=3)


def test_add_repo_drops_duplicates_and_nested():
    repos: list[Path] = []
    for path in ("/x/a", "/x/a", "/x/a/sub", "/x/b"):
        mod.add_repo(repos, Path(path))
    assert repos == [Path("/x/a"), Path("/x/b")]


def test_summary_block_is_everything_after_the_last_rule():
    rule = "─" * 45
    text = f"noise\n{rule}\nearlier\n\n{rule}\nSummary  2 branches\n\n  ✓ Updated  1   x\n"
    assert mod.summary_block(text) == "Summary  2 branches\n\n  ✓ Updated  1   x"
    assert mod.summary_block("a\nb\nc\nd\ne\nf\n") == "b\nc\nd\ne\nf"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(5, "5s ago"), (600, "10m ago"), (7200, "2h ago"), (259200, "3d ago")],
)
def test_ago(seconds, expected):
    assert mod.ago(1000, now=1000 + seconds) == expected


def test_fingerprint_modes_compare_their_own_hash():
    online = {"fingerprint": "full", "fingerprint_local": "local"}
    offline = {"fingerprint": None, "fingerprint_local": "local"}
    assert mod.Fingerprint("local", "full").matches(online, offline=False)
    assert mod.Fingerprint("local", None).matches(online, offline=True)
    # An entry an offline run wrote never satisfies an online run.
    assert not mod.Fingerprint("local", "full").matches(offline, offline=False)
    assert not mod.Fingerprint("other", None).matches(offline, offline=True)
