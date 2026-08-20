"""Tests for bin/files/delete-by-ext.py.

Every case from the old ``test/delete-by-ext.test.sh`` is carried over, plus
the cases the migration review turned up: a file named exactly ``.jpg``, a
symlinked root, ``--ext`` with a leading dot, and glob metacharacters in
``--ext``.
"""

from __future__ import annotations

SCRIPT = "files/delete-by-ext.py"

# The script defaults DRY_RUN=true (repo policy). Anything that expects a real
# delete must opt in explicitly, exactly as the .zshrc wrapper does.
REAL = {"DRY_RUN": "false"}


def test_deletes_matching_extensions(tmp_path, run_script):
    (tmp_path / "a.jpg").touch()
    (tmp_path / "b.png").touch()
    (tmp_path / "c.mp4").touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=jpg,png"], env=REAL)

    assert not (tmp_path / "a.jpg").exists()
    assert not (tmp_path / "b.png").exists()
    assert (tmp_path / "c.mp4").exists()


def test_dry_run_deletes_nothing(tmp_path, run_script):
    (tmp_path / "a.jpg").touch()
    (tmp_path / "b.png").touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=jpg,png", "--dry-run"])

    assert (tmp_path / "a.jpg").exists()
    assert (tmp_path / "b.png").exists()


def test_defaults_to_dry_run(tmp_path, run_script):
    """Repo policy: no DRY_RUN=false and no --dry-run=false means no deletes."""
    (tmp_path / "a.jpg").touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=jpg"])

    assert (tmp_path / "a.jpg").exists()


def test_filename_with_spaces(tmp_path, run_script):
    sub = tmp_path / "sub dir"
    sub.mkdir()
    (sub / "with spaces.jpg").touch()
    (sub / "keep.mp4").touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=jpg"], env=REAL)

    assert not (sub / "with spaces.jpg").exists()
    assert (sub / "keep.mp4").exists()


def test_filename_with_single_quote(tmp_path, run_script):
    target = tmp_path / "weird'quote.jpg"
    target.touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=jpg"], env=REAL)

    assert not target.exists()


def test_filename_with_newline(tmp_path, run_script):
    """Regression: a `find | grep | tr` pipeline split this into two paths."""
    target = tmp_path / "a\nb.jpg"
    target.touch()
    assert target.exists(), "setup: the OS must actually create the file"

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=jpg"], env=REAL)

    assert not target.exists()


def test_case_insensitive_extension(tmp_path, run_script):
    (tmp_path / "UPPER.JPG").touch()
    (tmp_path / "MiXeD.PnG").touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=jpg,png"], env=REAL)

    assert not (tmp_path / "UPPER.JPG").exists()
    assert not (tmp_path / "MiXeD.PnG").exists()


def test_recurses_into_subdirectories(tmp_path, run_script):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "deep.jpg").touch()
    (tmp_path / "a" / "keep.mp4").touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=jpg"], env=REAL)

    assert not (deep / "deep.jpg").exists()
    assert (tmp_path / "a" / "keep.mp4").exists()


def test_missing_path_errors(run_script):
    result = run_script(SCRIPT, ["--ext=jpg"])
    assert result.returncode != 0


def test_partial_extension_does_not_match(tmp_path, run_script):
    """`--ext=mpg` must anchor on the full extension, not a substring."""
    (tmp_path / "clip.mpeg").touch()
    (tmp_path / "clip.mpg").touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=mpg"], env=REAL)

    assert (tmp_path / "clip.mpeg").exists()
    assert not (tmp_path / "clip.mpg").exists()


def test_dotfile_named_only_extension_is_matched(tmp_path, run_script):
    """`find -iname '*.jpg'` matches a file literally named `.jpg`.

    A `Path.suffix` check would not, because pathlib treats a leading dot as
    the stem - that gap is what this case guards.
    """
    target = tmp_path / ".jpg"
    target.touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=jpg"], env=REAL)

    assert not target.exists()


def test_glob_metacharacters_in_ext(tmp_path, run_script):
    """`--ext=mp*` matched mp4/mp3/mpg when it was interpolated into -iname."""
    for name in ("a.mp4", "b.mp3", "c.mpg", "d.txt"):
        (tmp_path / name).touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=mp*"], env=REAL)

    assert not (tmp_path / "a.mp4").exists()
    assert not (tmp_path / "b.mp3").exists()
    assert not (tmp_path / "c.mpg").exists()
    assert (tmp_path / "d.txt").exists()


def test_leading_dot_in_ext_is_rejected(tmp_path, run_script):
    """`--ext=.jpg` built `-iname '*..jpg'` and matched nothing.

    Stripping the dot would silently turn a typo into a mass delete, so it is
    an error instead.
    """
    keep = tmp_path / "a.jpg"
    keep.touch()

    result = run_script(SCRIPT, [f"--path={tmp_path}", "--ext=.jpg"], env=REAL)

    assert result.returncode != 0
    assert keep.exists()


def test_symlinked_root_is_refused(tmp_path, run_script):
    """`find` does not follow a symlinked start point, so this was a no-op.

    Descending instead would turn `--path=~/media` (a symlink to the NAS) from
    "does nothing" into "deletes the library".
    """
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.jpg").touch()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    result = run_script(SCRIPT, [f"--path={link}", "--ext=jpg"], env=REAL)

    assert result.returncode != 0
    assert (real / "a.jpg").exists()


def test_bad_dry_run_value_is_rejected(tmp_path, run_script):
    """A typo must not be read as falsy and delete the user's files."""
    keep = tmp_path / "a.jpg"
    keep.touch()

    result = run_script(SCRIPT, [f"--path={tmp_path}", "--ext=jpg", "--dry-run=ture"])

    assert result.returncode != 0
    assert keep.exists()


def test_bare_dry_run_does_not_swallow_next_argument(tmp_path, run_script):
    """`--dry-run 0` must not parse as dry-run=False and delete for real."""
    keep = tmp_path / "a.jpg"
    keep.touch()

    run_script(SCRIPT, ["--dry-run", f"--path={tmp_path}", "--ext=jpg"], env=REAL)

    assert keep.exists()


def test_glob_extension_still_anchors_on_the_dot(tmp_path, run_script):
    """`--ext=mp*` must not match a file whose name merely contains 'mp'."""
    (tmp_path / "a.mp4").touch()
    (tmp_path / "important.txt").touch()

    run_script(SCRIPT, [f"--path={tmp_path}", "--ext=mp*"], env=REAL)

    assert not (tmp_path / "a.mp4").exists()
    assert (tmp_path / "important.txt").exists()
