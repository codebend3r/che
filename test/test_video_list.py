"""Tests for bin/video/video-list.py."""

from __future__ import annotations

SCRIPT = "video/video-list.py"


def test_no_color_means_no_escapes(tmp_path, run_script):
    """Regression: the coloured name and size were built by hand, so NO_COLOR leaked escapes."""
    library = tmp_path / "Movies"
    library.mkdir()
    (library / "a.mkv").write_bytes(b"abc")

    result = run_script(SCRIPT, [f"--path={library}", "--with-folder"])

    assert result.returncode == 0, result.stdout
    assert "\x1b" not in result.stdout
    assert result.stdout.splitlines()[-1] == "Movies/a.mkv [3 B]"


def test_force_color_paints_each_part(tmp_path, run_script):
    (tmp_path / "a.mkv").write_bytes(b"abc")

    result = run_script(SCRIPT, [f"--path={tmp_path}"], env={"NO_COLOR": "", "FORCE_COLOR": "1"})

    assert result.stdout.splitlines()[-1] == (
        "\x1b[0;32m\x1b[0;32ma.mkv\x1b[0m \x1b[1;33m[3 B]\x1b[0m\x1b[0m"
    )


def test_missing_path_is_an_error(run_script):
    result = run_script(SCRIPT, ["--path="])

    assert result.returncode == 1
    assert "❌ --path is required" in result.stdout
