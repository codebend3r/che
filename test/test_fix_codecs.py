"""Tests for bin/video/fix-codecs.py.

Only the dry run is exercised, so ffmpeg is never called: a stub on PATH
satisfies the binary check and fails loudly if anything does invoke it.
"""

from __future__ import annotations

import pytest

SCRIPT = "video/fix-codecs.py"


@pytest.fixture
def stub_ffmpeg(fake_bin):
    fake_bin("ffmpeg", "echo 'ffmpeg must not run in a dry run' >&2\nexit 99\n")


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "done.avi").touch()
    (root / "done_fixed.mp4").touch()
    (root / "todo.mkv").touch()
    return root


def test_dry_run_reports_the_skip_a_real_run_would_make(library, stub_ffmpeg, run_script):
    """Regression: the dry run promised to re-encode files whose output already existed."""
    result = run_script(SCRIPT, [f"--path={library}"], env={"DRY_RUN": ""})

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"⏭️  Skipping (output already exists): {library / 'done_fixed.mp4'}" in result.stdout
    assert f"Would re-encode: {library / 'done.avi'}" not in result.stdout
    assert (
        f"[DRY RUN] Would re-encode: {library / 'todo.mkv'} -> {library / 'todo_fixed.mp4'}"
        in result.stdout
    )
    assert f"⏭️  Skipping (already _fixed): {library / 'done_fixed.mp4'}" in result.stdout


def test_dry_run_changes_nothing(library, stub_ffmpeg, run_script):
    before = sorted(path.name for path in library.iterdir())

    run_script(SCRIPT, [f"--path={library}", "--delete-original"], env={"DRY_RUN": ""})

    assert sorted(path.name for path in library.iterdir()) == before
