"""Tests for bin/files/delete-empty-folders.py.

Carries over every case from the old ``test/delete-empty-folders.test.sh``.
"""

from __future__ import annotations

SCRIPT = "files/delete-empty-folders.py"

REAL = {"DRY_RUN": "false"}


def test_deletes_truly_empty_folder(tmp_path, run_script):
    empty = tmp_path / "empty"
    empty.mkdir()

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL)

    assert not empty.exists()


def test_preserves_folder_with_visible_files(tmp_path, run_script):
    keep = tmp_path / "keep"
    keep.mkdir()
    (keep / "file.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL)

    assert keep.exists()
    assert (keep / "file.txt").exists()


def test_preserves_hidden_only_folder(tmp_path, run_script):
    """Regression: a folder holding only .DS_Store is NOT empty.

    A recursive delete would silently wipe it; only strictly-empty folders go.
    """
    hidden = tmp_path / "hidden-only"
    hidden.mkdir()
    (hidden / ".DS_Store").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL)

    assert hidden.exists()
    assert (hidden / ".DS_Store").exists()


def test_cascades_nested_empties(tmp_path, run_script):
    chain = tmp_path / "a" / "b" / "c"
    chain.mkdir(parents=True)

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL)

    assert not (tmp_path / "a").exists()


def test_partial_cascade_stops_at_non_empty(tmp_path, run_script):
    chain = tmp_path / "a" / "b" / "c"
    chain.mkdir(parents=True)
    (tmp_path / "a" / "marker.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL)

    assert (tmp_path / "a").exists()
    assert not (tmp_path / "a" / "b").exists()


def test_does_not_delete_root(tmp_path, run_script):
    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL)
    assert tmp_path.exists()


def test_does_not_delete_root_with_trailing_slash(tmp_path, run_script):
    run_script(SCRIPT, [f"--path={tmp_path}/"], env=REAL)
    assert tmp_path.exists()


def test_dry_run_deletes_nothing(tmp_path, run_script):
    empty = tmp_path / "empty"
    empty.mkdir()

    run_script(SCRIPT, [f"--path={tmp_path}", "--dry-run"])

    assert empty.exists()


def test_defaults_to_dry_run(tmp_path, run_script):
    empty = tmp_path / "empty"
    empty.mkdir()

    run_script(SCRIPT, [f"--path={tmp_path}"])

    assert empty.exists()


def test_missing_path_errors(run_script):
    result = run_script(SCRIPT, [])
    assert result.returncode != 0


def test_folder_with_spaces(tmp_path, run_script):
    spaced = tmp_path / "some empty folder"
    spaced.mkdir()

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL)

    assert not spaced.exists()
