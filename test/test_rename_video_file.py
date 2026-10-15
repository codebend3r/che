"""Tests for bin/video/rename-video-file.py.

The title-casing is pinned through ``TitleCaser.file_name`` and
``TitleCaser.folder_name``; the folder walk runs end to end, since whether it
reaches below the top level is the part ``--recursive`` decides.
"""

from __future__ import annotations

import pytest
from conftest import load_script

SCRIPT = "video/rename-video-file.py"
rename = load_script(SCRIPT)
PLAIN = rename.TitleCaser.build([], capitalize_preps=False)
CURLY = "\N{RIGHT SINGLE QUOTATION MARK}"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("the movie - a tale of two cities.mkv", "The Movie - A Tale of Two Cities.mkv"),
        ("show-the end of the world.mkv", "Show - The End of the World.mkv"),
        ("ABC - 123 the thing.mp4", "ABC-123 The Thing.mp4"),
        (f"it{CURLY}s a boy's life.mkv", "It's a Boy's Life.mkv"),
        ("The Movie.mkv", "The Movie.mkv"),
    ],
)
def test_file_name(name, expected):
    assert PLAIN.file_name(name) == expected


def test_file_name_can_capitalize_prepositions():
    caser = rename.TitleCaser.build([], capitalize_preps=True)

    assert caser.file_name("an affair of the heart.mkv") == "An Affair Of The Heart.mkv"


def test_file_name_keeps_ignore_words_verbatim():
    caser = rename.TitleCaser.build(["iPhone"], capitalize_preps=False)

    assert caser.file_name("my iPhone video.mp4") == "My iPhone Video.mp4"


def test_file_name_refuses_a_dot_leading_name():
    """Renaming it would un-hide the file, as the shell version did."""
    assert PLAIN.file_name(".hidden movie.mkv") is None


def test_folder_name_straightens_curly_apostrophes():
    assert PLAIN.folder_name(f"l{CURLY}auberge") == "L'Auberge"


@pytest.fixture
def library(tmp_path):
    (tmp_path / "top one" / "nested two").mkdir(parents=True)
    return tmp_path


def folders(root):
    """The folder names under ``root`` as stored on disk.

    Listed rather than looked up, because on a case-insensitive filesystem
    ``(root / "Top One").is_dir()`` is true before any rename happens.
    """
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_dir())


def test_renames_only_top_level_folders_when_not_recursive(library, run_script):
    result = run_script(SCRIPT, [f"--path={library}", "--recursive=false", "--dry-run=false"])

    assert result.returncode == 0, result.stdout
    assert folders(library) == ["Top One", "Top One/nested two"]


def test_renames_nested_folders_deepest_first(library, run_script):
    result = run_script(SCRIPT, [f"--path={library}", "--dry-run=false"])

    assert result.returncode == 0, result.stdout
    assert folders(library) == ["Top One", "Top One/Nested Two"]


def test_defaults_to_dry_run(library, run_script):
    result = run_script(SCRIPT, [f"--path={library}"])

    assert "📁 [DRY RUN] Would rename folder: top one ➡️ Top One" in result.stdout
    assert folders(library) == ["top one", "top one/nested two"]
