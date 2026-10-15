"""Tests for bin/files/make-alpha-dir.py."""

from __future__ import annotations

import string

SCRIPT = "files/make-alpha-dir.py"

BUCKETS = {"#", *string.ascii_uppercase}


def test_creates_all_27_buckets_and_the_parent(tmp_path, run_script):
    parent = tmp_path / "Movies" / "4K"

    run_script(SCRIPT, [f"--path={parent}"], check=True)

    assert {path.name for path in parent.iterdir() if path.is_dir()} == BUCKETS


def test_defaults_to_the_current_directory(tmp_path, run_script):
    run_script(SCRIPT, [], cwd=tmp_path, check=True)

    assert {path.name for path in tmp_path.iterdir()} == BUCKETS


def test_rerunning_is_harmless(tmp_path, run_script):
    run_script(SCRIPT, [f"--path={tmp_path}"], check=True)
    (tmp_path / "A" / "Alien (1979)").mkdir()

    run_script(SCRIPT, [f"--path={tmp_path}"], check=True)

    assert (tmp_path / "A" / "Alien (1979)").is_dir()


def test_a_file_in_the_way_fails_that_bucket_only(tmp_path, run_script):
    """`mkdir -p -- '#' {A..Z}` reported the clash and still made the other 26."""
    (tmp_path / "A").write_text("not a folder")

    result = run_script(SCRIPT, [f"--path={tmp_path}"])

    assert result.returncode == 1
    assert "mkdir: A:" in result.stdout
    assert (tmp_path / "A").is_file()
    assert {path.name for path in tmp_path.iterdir() if path.is_dir()} == BUCKETS - {"A"}
