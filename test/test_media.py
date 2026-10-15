"""Tests for bin/media.py.

``probe_media`` replaced one ffprobe call per field with a single JSON probe.
The JSON writer omits fields the csv and default writers printed as
``unknown`` or ``N/A``, so these pin the accessors to the values the
per-field calls returned. Most stub ffprobe with canned JSON; the last runs
the real one when it is installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import media
import pytest
from media import MediaProbe, probe_media

# Shaped like ffprobe 9's real output for -show_entries
# stream=codec_type,codec_name,width:stream_tags=language:format=bit_rate.
FULL = {
    "programs": [],
    "stream_groups": [],
    "streams": [
        {"index": 0, "codec_name": "h264", "codec_type": "video", "width": 1920, "tags": {}},
        {"index": 1, "codec_name": "aac", "codec_type": "audio", "tags": {"language": "jpn"}},
        {"index": 2, "codec_name": "ac3", "codec_type": "audio", "tags": {"language": "eng"}},
        {"index": 3, "codec_name": "aac", "codec_type": "audio", "tags": {"language": "eng"}},
        {"index": 4, "codec_name": "subrip", "codec_type": "subtitle", "tags": {}},
    ],
    "format": {"bit_rate": "8000000"},
}


@pytest.fixture
def ffprobe_says(monkeypatch):
    """Stub the ffprobe call: ``ffprobe_says(returncode, stdout)``."""

    def _stub(returncode: int, stdout: str) -> None:
        def fake_run(argv, **_kwargs):
            return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

        monkeypatch.setattr(media, "run", fake_run)

    return _stub


def test_probe_media_parses_the_json(ffprobe_says, tmp_path):
    ffprobe_says(0, json.dumps(FULL))

    result = probe_media(tmp_path / "a.mkv")

    assert result == MediaProbe.from_json(FULL)


def test_probe_media_is_none_when_ffprobe_fails(ffprobe_says, tmp_path):
    ffprobe_says(1, "")

    assert probe_media(tmp_path / "corrupt.mkv") is None


def test_probe_media_is_none_on_unparseable_output(ffprobe_says, tmp_path):
    ffprobe_says(0, "{not json")

    assert probe_media(tmp_path / "a.mkv") is None


def test_codec_reads_the_first_stream_of_each_kind():
    result = MediaProbe.from_json(FULL)

    assert result.codec("video") == "h264"
    assert result.codec("audio") == "aac"  # a:0, not the later ac3
    assert result.codec("subtitle") == "subrip"


def test_codec_is_empty_when_there_is_no_such_stream():
    result = MediaProbe.from_json({"streams": [{"codec_name": "h264", "codec_type": "video"}]})

    assert result.codec("audio") == ""
    assert result.codec("subtitle") == ""


def test_codec_is_unknown_when_ffprobe_cannot_name_it():
    """JSON omits codec_name where the per-field calls printed "unknown"."""
    result = MediaProbe.from_json(
        {"streams": [{"codec_type": "audio", "tags": {"language": "eng"}}]}
    )

    assert result.codec("audio") == "unknown"


def test_width_and_bit_rate_are_numbers():
    result = MediaProbe.from_json(FULL)

    assert result.width() == 1920
    assert result.bit_rate() == 8_000_000


def test_a_zero_width_is_a_number_not_missing():
    result = MediaProbe.from_json({"streams": [{"codec_type": "video", "width": 0}]})

    assert result.width() == 0


def test_missing_width_and_bit_rate_are_none():
    """The per-field calls printed nothing / "N/A"; neither is numeric."""
    result = MediaProbe.from_json(
        {"streams": [{"codec_name": "aac", "codec_type": "audio"}], "format": {"bit_rate": "N/A"}}
    )

    assert result.width() is None
    assert result.bit_rate() is None


def test_languages_are_sorted_and_deduplicated():
    assert MediaProbe.from_json(FULL).languages("audio") == ["eng", "jpn"]


def test_languages_skip_untagged_and_blank_streams():
    result = MediaProbe.from_json(
        {
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "audio", "codec_name": "aac", "tags": {}},
                {"codec_type": "audio", "codec_name": "aac", "tags": {"language": "  "}},
                {"codec_type": "video", "codec_name": "h264", "tags": {"language": "fre"}},
            ]
        }
    )

    assert result.languages("audio") == []


def test_languages_match_the_tag_key_case_insensitively():
    """-show_entries stream_tags=language matched a LANGUAGE tag too."""
    result = MediaProbe.from_json(
        {"streams": [{"codec_type": "audio", "tags": {"LANGUAGE": " spa "}}]}
    )

    assert result.languages("audio") == ["spa"]


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg and ffprobe"
)
def test_against_the_real_ffprobe(tmp_path):
    sample = tmp_path / "sample.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x48:rate=5:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "mp2",
            "-metadata:s:a:0",
            "language=eng",
            str(sample),
        ],
        check=True,
    )
    corrupt = tmp_path / "corrupt.mkv"
    corrupt.write_bytes(b"\x00" * 4096)

    result = probe_media(sample)

    assert result is not None
    assert (result.codec("video"), result.codec("audio"), result.codec("subtitle")) == (
        "mpeg4",
        "mp2",
        "",
    )
    assert result.width() == 64
    assert isinstance(result.bit_rate(), int)
    assert result.languages("audio") == ["eng"]
    assert probe_media(corrupt) is None
