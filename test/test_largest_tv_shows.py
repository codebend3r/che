"""Tests for bin/video/largest-tv-shows.py."""

from __future__ import annotations

import os

import pytest
from conftest import load_script

SCRIPT = "video/largest-tv-shows.py"
shows = load_script(SCRIPT)


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "TV"
    for folder, size in (
        ("Big Show/Season 1", 200_000),
        ("Small Show/Season 01", 20_000),
        ("Not A Show/Extras", 500_000),
    ):
        (root / folder).mkdir(parents=True)
        (root / folder / "episode.mkv").write_bytes(b"x" * size)
    # A season folder reached only through a symlink does not make a show.
    (root / "Linked Show").mkdir()
    (root / "Linked Show" / "Season 1").symlink_to(root / "Big Show" / "Season 1")
    return root


def test_is_tv_show_folder_matches_a_season_child(tmp_path):
    assert shows.is_tv_show_folder(tmp_path, ["Extras", "Season 12"])
    assert not shows.is_tv_show_folder(tmp_path, ["Season", "Season 1x", "Seasons 1"])


def test_is_tv_show_folder_ignores_a_symlinked_season(library):
    show = library / "Linked Show"

    assert not shows.is_tv_show_folder(show, ["Season 1"])


def test_folder_size_counts_a_hard_link_once(library):
    season = library / "Big Show" / "Season 1"
    before = shows.folder_size(season)

    os.link(season / "episode.mkv", season / "episode copy.mkv")

    assert shows.folder_size(season) == before


def test_ranks_shows_by_size(library, run_script):
    result = run_script(SCRIPT, [f"--path={library}"])

    assert result.returncode == 0, result.stdout
    assert "Detected 2 TV show folder(s)" in result.stdout
    listed = result.stdout.splitlines()[-2:]
    assert [line.split(maxsplit=2)[-1] for line in listed] == ["Big Show", "Small Show"]


@pytest.mark.parametrize("limit", ["0", "+5", "x"])
def test_rejects_a_limit_that_is_not_a_positive_integer(library, run_script, limit):
    result = run_script(SCRIPT, [f"--path={library}", f"--limit={limit}"])

    assert result.returncode == 1
    assert f"❌ --limit must be a positive integer (got: {limit})" in result.stdout
