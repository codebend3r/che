"""Tests for bin/files/delete-empty-folders.py.

Carries over every case from the old ``test/delete-empty-folders.test.sh``.
"""

from __future__ import annotations

SCRIPT = "files/delete-empty-folders.py"

REAL = {"DRY_RUN": "false"}


def test_deletes_truly_empty_folder(tmp_path, run_script):
    empty = tmp_path / "empty"
    empty.mkdir()

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL, check=True)

    assert not empty.exists()


def test_preserves_folder_with_visible_files(tmp_path, run_script):
    keep = tmp_path / "keep"
    keep.mkdir()
    (keep / "file.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL, check=True)

    assert keep.exists()
    assert (keep / "file.txt").exists()


def test_preserves_hidden_only_folder(tmp_path, run_script):
    """Regression: a folder holding only .DS_Store is NOT empty.

    A recursive delete would silently wipe it; only strictly-empty folders go.
    """
    hidden = tmp_path / "hidden-only"
    hidden.mkdir()
    (hidden / ".DS_Store").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL, check=True)

    assert hidden.exists()
    assert (hidden / ".DS_Store").exists()


def test_cascades_nested_empties(tmp_path, run_script):
    chain = tmp_path / "a" / "b" / "c"
    chain.mkdir(parents=True)

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL, check=True)

    assert not (tmp_path / "a").exists()


def test_partial_cascade_stops_at_non_empty(tmp_path, run_script):
    chain = tmp_path / "a" / "b" / "c"
    chain.mkdir(parents=True)
    (tmp_path / "a" / "marker.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL, check=True)

    assert (tmp_path / "a").exists()
    assert not (tmp_path / "a" / "b").exists()


def test_does_not_delete_root(tmp_path, run_script):
    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL, check=True)
    assert tmp_path.exists()


def test_does_not_delete_root_with_trailing_slash(tmp_path, run_script):
    run_script(SCRIPT, [f"--path={tmp_path}/"], env=REAL, check=True)
    assert tmp_path.exists()


def test_dry_run_deletes_nothing(tmp_path, run_script):
    empty = tmp_path / "empty"
    empty.mkdir()

    run_script(SCRIPT, [f"--path={tmp_path}", "--dry-run"], check=True)

    assert empty.exists()


def test_defaults_to_dry_run(tmp_path, run_script):
    empty = tmp_path / "empty"
    empty.mkdir()

    run_script(SCRIPT, [f"--path={tmp_path}"], check=True)

    assert empty.exists()


def test_missing_path_errors(run_script):
    result = run_script(SCRIPT, [])
    assert result.returncode != 0


def test_folder_with_spaces(tmp_path, run_script):
    spaced = tmp_path / "some empty folder"
    spaced.mkdir()

    run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL, check=True)

    assert not spaced.exists()


def reported(stdout: str, prefix: str) -> list[str]:
    return [line.removeprefix(prefix) for line in stdout.splitlines() if line.startswith(prefix)]


def test_dry_run_previews_the_whole_empty_chain(tmp_path, run_script):
    """The real run deletes a/b/c; the shell version previewed only `c`."""
    chain = tmp_path / "a" / "b" / "c"
    chain.mkdir(parents=True)

    result = run_script(SCRIPT, [f"--path={tmp_path}", "--dry-run"], check=True)

    assert reported(result.stdout, "[DRY-RUN] Would delete: ") == [
        str(chain),
        str(chain.parent),
        str(chain.parent.parent),
    ]
    assert "📊 Total deleted directories: 3" in result.stdout
    assert chain.exists()


def test_dry_run_previews_exactly_what_a_real_run_deletes(tmp_path, run_script):
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    (tmp_path / "a" / "b2").mkdir()
    (tmp_path / "keep" / "x" / "y").mkdir(parents=True)
    (tmp_path / "keep" / "file.txt").touch()
    (tmp_path / "hidden" / "z").mkdir(parents=True)
    (tmp_path / "hidden" / ".DS_Store").touch()

    preview = run_script(SCRIPT, [f"--path={tmp_path}", "--dry-run"], check=True)
    real = run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL, check=True)

    previewed = reported(preview.stdout, "[DRY-RUN] Would delete: ")
    assert previewed == reported(real.stdout, "Deleted: ")
    assert sorted(previewed) == sorted(
        str(tmp_path / rel)
        for rel in ("a", "a/b", "a/b/c", "a/b2", "keep/x", "keep/x/y", "hidden/z")
    )
