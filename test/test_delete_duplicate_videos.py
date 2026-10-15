"""Tests for bin/video/delete-duplicate-videos.py.

``group_key`` is tested per strategy, including the order its side effects
happen in: for ``all`` an unreadable size skips the file before it is hashed.
The end-to-end cases cover the keeper choice and the dry-run default.
"""

from __future__ import annotations

import hashlib

import pytest
from conftest import load_script

SCRIPT = "video/delete-duplicate-videos.py"
dedupe = load_script(SCRIPT)
RS = dedupe.KEY_RS


@pytest.fixture
def episode(tmp_path):
    path = tmp_path / "Show - S01E02 - Pilot.mkv"
    path.write_bytes(b"x" * 10)
    return path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_episode_key_is_folder_and_episode_code(episode):
    assert dedupe.group_key(episode, "episode", verbose=False) == f"{episode.parent}{RS}S01E02"


def test_episode_key_skips_names_without_a_code(tmp_path):
    path = tmp_path / "Movie.mkv"
    path.touch()

    assert dedupe.group_key(path, "episode", verbose=False) is None


def test_filename_key_is_folder_and_name(episode):
    assert dedupe.group_key(episode, "filename", verbose=False) == (
        f"{episode.parent}{RS}{episode.name}"
    )


def test_size_key_is_folder_and_size(episode):
    assert dedupe.group_key(episode, "size", verbose=False) == f"{episode.parent}{RS}10"


def test_size_key_skips_an_unreadable_file(tmp_path, capsys):
    missing = tmp_path / "gone.mkv"

    assert dedupe.group_key(missing, "size", verbose=False) is None
    assert f"SKIP: unreadable size: {missing}" in capsys.readouterr().out


def test_hash_key_is_the_digest_alone(episode, capsys):
    assert dedupe.group_key(episode, "hash", verbose=True) == sha256(episode)
    assert f"HASH: {episode}" in capsys.readouterr().out


def test_all_key_joins_every_field(episode):
    assert dedupe.group_key(episode, "all", verbose=False) == RS.join(
        (str(episode.parent), episode.name, "10", sha256(episode))
    )


def test_all_key_skips_on_size_before_hashing(tmp_path, capsys):
    missing = tmp_path / "gone.mkv"

    assert dedupe.group_key(missing, "all", verbose=True) is None
    out = capsys.readouterr().out
    assert "SKIP: unreadable size" in out
    assert "HASH:" not in out


def test_an_unknown_key_field_is_an_error(episode):
    """A misspelled STRATEGY_FIELDS entry must not fall through to hashing."""
    with pytest.raises(ValueError, match="unknown key field: dgest"):
        dedupe.key_field(episode, "dgest", verbose=False)


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


def test_defaults_to_dry_run(tmp_path, run_script):
    files = [tmp_path / "Show - S01E01 - a.mkv", tmp_path / "Show - S01E01 - b.mkv"]
    for path in files:
        path.write_bytes(b"x")

    # Empty, not absent: an exported DRY_RUN=false in the caller's shell must
    # not turn this into a real delete.
    result = run_script(SCRIPT, [f"--path={tmp_path}"], env={"DRY_RUN": ""})

    assert "[DRY-RUN] ❌ Would delete:" in result.stdout
    assert all(path.exists() for path in files)
