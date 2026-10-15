"""Tests for bin/files/find-largest-files.py."""

from __future__ import annotations

import re

SCRIPT = "files/find-largest-files.py"

# One listing line: the size right-aligned in 12 columns, two spaces, the name.
_LISTING = re.compile(r"^ *[0-9.]+ [KMGTP]?B  (.*)$")


def sized(path, size: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)


def listed(stdout: str) -> list[str]:
    return [match[1] for line in stdout.splitlines() if (match := _LISTING.match(line))]


def test_biggest_first(tmp_path, run_script):
    sized(tmp_path / "small.bin", 1)
    sized(tmp_path / "sub" / "big.bin", 3000)
    sized(tmp_path / "medium.bin", 20)

    result = run_script(SCRIPT, [f"--path={tmp_path}"], check=True)

    assert listed(result.stdout) == ["big.bin", "medium.bin", "small.bin"]
    assert "     2.92 KB  big.bin" in result.stdout


def test_ties_break_on_the_path_descending(tmp_path, run_script):
    """`sort -nr` reverses its last-resort whole-line comparison too."""
    for name in ("a.bin", "c.bin", "b.bin"):
        sized(tmp_path / name, 5)

    result = run_script(SCRIPT, [f"--path={tmp_path}"], check=True)

    assert listed(result.stdout) == ["c.bin", "b.bin", "a.bin"]


def test_length_limits_the_listing(tmp_path, run_script):
    for size in range(1, 6):
        sized(tmp_path / f"{size}.bin", size)

    result = run_script(SCRIPT, [f"--path={tmp_path}", "--length=2"], check=True)

    assert listed(result.stdout) == ["5.bin", "4.bin"]


def test_full_path_keeps_the_dot_of_the_default_path(tmp_path, run_script):
    """`find .` printed `./name`; anything piping this into xargs relies on it."""
    sized(tmp_path / "sub" / "big.bin", 10)

    result = run_script(SCRIPT, ["--full-path"], cwd=tmp_path, check=True)

    assert listed(result.stdout) == ["./sub/big.bin"]


def test_full_path_with_a_trailing_slash(tmp_path, run_script):
    sized(tmp_path / "big.bin", 10)

    result = run_script(SCRIPT, [f"--path={tmp_path}/", "--full-path"], check=True)

    assert listed(result.stdout) == [f"{tmp_path}/big.bin"]


def test_non_numeric_length_is_rejected(tmp_path, run_script):
    result = run_script(SCRIPT, [f"--path={tmp_path}", "--length=x"])

    assert result.returncode == 1
    assert "❌ --length must be a non-negative integer (got: x)" in result.stdout
