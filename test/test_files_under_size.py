"""Tests for bin/files/files-under-size.py."""

from __future__ import annotations

SCRIPT = "files/files-under-size.py"

# The script defaults DRY_RUN=true (repo policy). Anything that expects a real
# delete must opt in explicitly, exactly as the generated wrapper does.
REAL = {"DRY_RUN": "false"}


def sized(path, size: int):
    path.write_bytes(b"\0" * size)
    return path


def test_threshold_is_inclusive(tmp_path, run_script):
    """`find -size -Nc` with N = limit + 1 selected files of AT MOST the limit."""
    at = sized(tmp_path / "at.mp4", 1024)
    over = sized(tmp_path / "over.mp4", 1025)

    run_script(SCRIPT, [f"--path={tmp_path}", "--size=1k"], env=REAL, check=True)

    assert not at.exists()
    assert over.exists()


def test_only_video_extensions_match(tmp_path, run_script):
    (tmp_path / "sub").mkdir()
    video = sized(tmp_path / "sub" / "clip.MKV", 10)
    text = sized(tmp_path / "notes.txt", 10)
    image = sized(tmp_path / "poster.jpg", 10)

    run_script(SCRIPT, [f"--path={tmp_path}", "--size=1k"], env=REAL, check=True)

    assert not video.exists()
    assert text.exists()
    assert image.exists()


def test_defaults_to_preview(tmp_path, run_script):
    small = sized(tmp_path / "small.mp4", 10)

    result = run_script(SCRIPT, [f"--path={tmp_path}", "--size=1k"], check=True)

    assert small.exists()
    assert f"[1/1] Would delete: 10 B - {small}" in result.stdout


def test_nothing_under_the_threshold(tmp_path, run_script):
    sized(tmp_path / "big.mp4", 2048)

    result = run_script(SCRIPT, [f"--path={tmp_path}", "--size=1k"], env=REAL, check=True)

    assert "No matching video files ≤ 1k (1024 bytes)." in result.stdout


def test_terabytes_are_rejected(tmp_path, run_script):
    """The shell version had no terabyte unit; accepting one would sweep a library."""
    small = sized(tmp_path / "small.mp4", 10)

    result = run_script(SCRIPT, [f"--path={tmp_path}", "--size=1t"], env=REAL)

    assert result.returncode == 1
    assert small.exists()


def test_size_and_path_are_required(tmp_path, run_script):
    assert run_script(SCRIPT, [f"--path={tmp_path}"]).returncode == 1
    assert run_script(SCRIPT, ["--size=1k"]).returncode == 1
