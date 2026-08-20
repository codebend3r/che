"""Tests for bin/files/compress-folders.py.

Carries over every case from the old ``test/compress-folders.test.sh``, plus
the archive-content gaps the migration review found: the top-level directory
entry, empty subfolders, dotted subfolders, and symlink dereferencing.

The old suite skipped itself when ``zip``/``unzip`` were missing. These tests
read archives with the stdlib ``zipfile``, so there is nothing to skip.
"""

from __future__ import annotations

import zipfile

SCRIPT = "files/compress-folders.py"


def entries(archive) -> set[str]:
    with zipfile.ZipFile(archive) as zf:
        return set(zf.namelist())


def test_zips_each_immediate_subfolder(tmp_path, run_script):
    (tmp_path / "foo").mkdir()
    (tmp_path / "bar").mkdir()
    (tmp_path / "foo" / "a.txt").touch()
    (tmp_path / "bar" / "b.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"])

    assert (tmp_path / "foo.zip").is_file()
    assert (tmp_path / "bar.zip").is_file()
    assert "foo/a.txt" in entries(tmp_path / "foo.zip")
    assert "bar/b.txt" in entries(tmp_path / "bar.zip")


def test_archive_contains_the_top_level_directory_entry(tmp_path, run_script):
    """`zip -r` writes `foo/` first; without it an empty folder archives to nothing."""
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "a.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"])

    assert "foo/" in entries(tmp_path / "foo.zip")


def test_empty_subfolder_survives_the_round_trip(tmp_path, run_script):
    (tmp_path / "empty").mkdir()

    run_script(SCRIPT, [f"--path={tmp_path}"])

    assert "empty/" in entries(tmp_path / "empty.zip")


def test_nested_empty_directory_is_preserved(tmp_path, run_script):
    (tmp_path / "outer" / "hollow").mkdir(parents=True)
    (tmp_path / "outer" / "a.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"])

    assert "outer/hollow/" in entries(tmp_path / "outer.zip")


def test_does_not_zip_nested_subfolders_separately(tmp_path, run_script):
    (tmp_path / "outer" / "inner").mkdir(parents=True)
    (tmp_path / "outer" / "inner" / "deep.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"])

    assert (tmp_path / "outer.zip").is_file()
    assert not (tmp_path / "inner.zip").exists()
    assert "outer/inner/deep.txt" in entries(tmp_path / "outer.zip")


def test_dotted_subfolders_are_skipped(tmp_path, run_script):
    """`for dir in "$ROOT"/*/` has no dotglob, so `.git` was never zipped."""
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "a.txt").touch()
    (tmp_path / "normal").mkdir()
    (tmp_path / "normal" / "b.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"])

    assert (tmp_path / "normal.zip").is_file()
    assert not (tmp_path / ".hidden.zip").exists()


def test_symlinked_content_is_dereferenced(tmp_path, run_script):
    """`zip -r` follows symlinks by default; skipping them would drop content."""
    folder = tmp_path / "foo"
    folder.mkdir()
    (folder / "real.txt").write_text("payload")
    (folder / "link.txt").symlink_to(folder / "real.txt")

    run_script(SCRIPT, [f"--path={tmp_path}"])

    names = entries(tmp_path / "foo.zip")
    assert "foo/link.txt" in names
    with zipfile.ZipFile(tmp_path / "foo.zip") as zf:
        assert zf.read("foo/link.txt") == b"payload"


def test_stale_entries_are_dropped_on_rerun(tmp_path, run_script):
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "old.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"])
    assert "foo/old.txt" in entries(tmp_path / "foo.zip")

    (tmp_path / "foo" / "old.txt").unlink()
    (tmp_path / "foo" / "new.txt").touch()
    run_script(SCRIPT, [f"--path={tmp_path}"])

    names = entries(tmp_path / "foo.zip")
    assert "foo/new.txt" in names
    assert "foo/old.txt" not in names


def test_folder_with_spaces(tmp_path, run_script):
    folder = tmp_path / "my folder"
    folder.mkdir()
    (folder / "file.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"])

    assert (tmp_path / "my folder.zip").is_file()
    assert "my folder/file.txt" in entries(tmp_path / "my folder.zip")


def test_dry_run_creates_no_archives(tmp_path, run_script):
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "a.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--dry-run"])

    assert not (tmp_path / "foo.zip").exists()


def test_no_partial_file_is_left_behind(tmp_path, run_script):
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "a.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"])

    assert not list(tmp_path.glob("*.partial"))


def test_missing_path_errors(run_script):
    result = run_script(SCRIPT, [])
    assert result.returncode != 0


def test_empty_parent_is_a_noop(tmp_path, run_script):
    result = run_script(SCRIPT, [f"--path={tmp_path}"])
    assert result.returncode == 0
