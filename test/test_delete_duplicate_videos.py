"""Tests for bin/video/delete-duplicate-videos.py.

``group_key`` is tested per strategy, including the order its side effects
happen in: for ``all`` an unreadable size skips the file before it is hashed.
The end-to-end cases cover the keeper choice and the dry-run default.
"""

from __future__ import annotations

import hashlib

import pytest
from conftest import load_script, summary

SCRIPT = "video/delete-duplicate-videos.py"
dedupe = load_script(SCRIPT)


@pytest.fixture
def episode(tmp_path):
    path = tmp_path / "Show - S01E02 - Pilot.mkv"
    path.write_bytes(b"x" * 10)
    return path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def never(path, reason):
    raise AssertionError(f"unexpected skip of {path}: {reason}")


def key(path, strategy, *, verbose=False, skip=never):
    return dedupe.group_key(path, strategy, verbose=verbose, skip=skip)


def test_episode_key_is_folder_and_episode_code(episode):
    assert key(episode, "episode") == (str(episode.parent), "S01E02")


def test_episode_key_skips_names_without_a_code(tmp_path):
    path = tmp_path / "Movie.mkv"
    path.touch()

    assert key(path, "episode") is None


def test_filename_key_is_folder_and_name(episode):
    assert key(episode, "filename") == (str(episode.parent), episode.name)


def test_size_key_is_folder_and_size(episode):
    assert key(episode, "size") == (str(episode.parent), "10")


def test_size_key_skips_an_unreadable_file(tmp_path):
    missing = tmp_path / "gone.mkv"
    skipped = []

    assert key(missing, "size", skip=lambda *args: skipped.append(args)) is None
    assert skipped == [(missing, "unreadable size")]


def test_hash_key_is_the_digest_alone(episode, capsys):
    assert key(episode, "hash", verbose=True) == (sha256(episode),)
    assert f"HASH: {episode}" in capsys.readouterr().out


def test_all_key_joins_every_field(episode):
    assert key(episode, "all") == (str(episode.parent), episode.name, "10", sha256(episode))


def test_all_key_skips_on_size_before_hashing(tmp_path, capsys):
    missing = tmp_path / "gone.mkv"
    skipped = []

    assert key(missing, "all", verbose=True, skip=lambda *args: skipped.append(args)) is None
    assert skipped == [(missing, "unreadable size")]
    assert "HASH:" not in capsys.readouterr().out


def test_every_strategy_has_fields():
    assert set(dedupe.STRATEGY_ALIASES.values()) == set(dedupe.STRATEGY_FIELDS)


def test_deletes_the_smaller_copy(tmp_path, run_script):
    keep = tmp_path / "Show - S01E01 - 1080p.mkv"
    drop = tmp_path / "Show - S01E01 - 720p.mp4"
    keep.write_bytes(b"x" * 100)
    drop.write_bytes(b"x" * 50)

    result = run_script(SCRIPT, [f"--path={tmp_path}"], env={"DRY_RUN": "false"})

    assert result.returncode == 0, result.stdout
    assert keep.exists()
    assert not drop.exists()
    rows = summary(result.stdout)
    assert rows["Deleted"] == [drop.name]
    assert "Kept (largest copy)" in rows


def test_defaults_to_dry_run(tmp_path, run_script):
    files = [tmp_path / "Show - S01E01 - a.mkv", tmp_path / "Show - S01E01 - b.mkv"]
    for path in files:
        path.write_bytes(b"x")

    # Empty, not absent: an exported DRY_RUN=false in the caller's shell must
    # not turn this into a real delete.
    result = run_script(SCRIPT, [f"--path={tmp_path}"], env={"DRY_RUN": ""})

    assert summary(result.stdout)["Would delete"] == [files[1].name]
    assert all(path.exists() for path in files)
