"""Tests for bin/video/find-video-mkv-issues.py.

The scoring and tiering are pure and tested directly. The summary block runs
end to end against the real ffprobe, so it is skipped where that is missing.
"""

from __future__ import annotations

import shutil

import pytest
from conftest import load_script

SCRIPT = "video/find-video-mkv-issues.py"
mkv = load_script(SCRIPT)


@pytest.mark.parametrize(
    ("score", "label"),
    [
        (10, "Excellent"),
        (9, "Excellent"),
        (8, "Good"),
        (7, "Good"),
        (6, "Poor"),
        (4, "Poor"),
        (3, "Bad"),
        (0, "Bad"),
    ],
)
def test_tier_boundaries(score, label):
    assert mkv.tier(score).label == label


def test_rate_video_perfect_file():
    assert mkv.rate_video("h264", "aac", "none", 1920, 5_000_000) == (
        10,
        "Excellent Plex compatibility",
    )


def test_rate_video_stacks_penalties_and_joins_reasons():
    score, notes = mkv.rate_video("hevc", "dts", "hdmv_pgs_subtitle", 3840, 70_000_000)

    assert score == 10 - 1 - 3 - 2 - 1 - 2
    assert notes == (
        "HEVC may transcode on older clients;DTS unsupported on many TVs/mobile devices;"
        "PGS subtitles may force transcoding;4K playback may struggle on weaker devices;"
        "Very high bitrate"
    )


def test_rate_video_unknown_codecs_take_the_default_penalty_and_clamp_at_zero():
    """10 - 8 - 4 is -2, which clamps to 0."""
    assert mkv.rate_video("unknown", "unknown", "none", 0, 0) == (
        0,
        "Unknown or niche video codec;Unknown or niche audio codec",
    )


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="needs ffprobe")
def test_corrupt_file_counts_as_bad_in_the_summary(tmp_path, run_script):
    (tmp_path / "broken.mkv").write_bytes(b"\x00" * 4096)

    result = run_script(SCRIPT, [f"--path={tmp_path}"])

    assert result.returncode == 0, result.stdout
    assert "  Corrupt or unreadable file" in result.stdout
    assert result.stdout.endswith(
        "Total Files : 1\nExcellent   : 0\nGood        : 0\nPoor        : 0\nBad         : 1\n"
    )
