"""Tests for bin/files/make-alpha-dir.py."""

from __future__ import annotations

import re
import string

from conftest import summary

SCRIPT = "files/make-alpha-dir.py"

BUCKETS = {"#", *string.ascii_uppercase}


def test_creates_all_27_buckets_and_the_parent(tmp_path, run_script):
    parent = tmp_path / "Movies" / "4K"

    result = run_script(SCRIPT, [f"--path={parent}"], check=True)

    assert {path.name for path in parent.iterdir() if path.is_dir()} == BUCKETS
    created = re.findall(r"^  \+ created +(\S)$", result.stdout, re.M)
    assert set(created) == BUCKETS
    assert summary(result.stdout)["Created"][-1] == "… and 17 more"


def test_defaults_to_the_current_directory(tmp_path, run_script):
    run_script(SCRIPT, [], cwd=tmp_path, check=True)

    assert {path.name for path in tmp_path.iterdir()} == BUCKETS


def test_rerunning_is_harmless(tmp_path, run_script):
    run_script(SCRIPT, [f"--path={tmp_path}"], check=True)
    (tmp_path / "A" / "Alien (1979)").mkdir()

    result = run_script(SCRIPT, [f"--path={tmp_path}"], check=True)

    assert (tmp_path / "A" / "Alien (1979)").is_dir()
    assert summary(result.stdout) == {"Already there": []}


def test_a_file_in_the_way_fails_that_bucket_only(tmp_path, run_script):
    """`mkdir -p -- '#' {A..Z}` reported the clash and still made the other 26."""
    (tmp_path / "A").write_text("not a folder")

    result = run_script(SCRIPT, [f"--path={tmp_path}"])

    assert result.returncode == 1
    assert summary(result.stdout)["Failed"] == ["A: File exists"]
    assert (tmp_path / "A").is_file()
    assert {path.name for path in tmp_path.iterdir() if path.is_dir()} == BUCKETS - {"A"}
