"""Tests for bin/files/delete-smb-files.py."""

from __future__ import annotations

SCRIPT = "files/delete-smb-files.py"

# The script defaults DRY_RUN=true (repo policy). Anything that expects a real
# delete must opt in explicitly, exactly as the generated wrapper does.
REAL = {"DRY_RUN": "false"}


def tree(tmp_path):
    """Placeholders at the top and two levels down, among files to keep."""
    deep = tmp_path / "Movies" / "Alien (1979)"
    deep.mkdir(parents=True)
    junk = [tmp_path / ".smbdelete0001", deep / ".smbdeleteA1B2C3"]
    keep = [
        tmp_path / "Movies" / "notes.txt",
        deep / "Alien (1979).mkv",
        deep / "smbdelete-without-the-dot",
        # `find -name '.smbdelete*'` is case-sensitive and anchored at the
        # start of the name, so neither of these was ever matched.
        deep / ".SMBDELETE0002",
        deep / "._.smbdelete0003",
    ]
    for path in junk + keep:
        path.touch()
    return junk, keep


def test_removes_nested_placeholders_and_nothing_else(tmp_path, run_script):
    junk, keep = tree(tmp_path)

    result = run_script(SCRIPT, [f"--path={tmp_path}"], env=REAL, check=True)

    assert [path for path in junk if path.exists()] == []
    assert [path for path in keep if not path.exists()] == []
    assert "📊 Deleted 2 file(s)." in result.stdout


def test_defaults_to_preview(tmp_path, run_script):
    junk, _ = tree(tmp_path)

    result = run_script(SCRIPT, [f"--path={tmp_path}"], check=True)

    assert all(path.exists() for path in junk)
    for path in junk:
        assert f"{path}\n" in result.stdout
    assert "Deleted" not in result.stdout


def test_missing_path_errors(run_script):
    assert run_script(SCRIPT, []).returncode == 1
