"""Tests for bin/system/update-brew.py.

A fake ``brew`` first on PATH records each call's arguments, one call per
line, so the suite checks exactly which Homebrew commands a run would issue
without touching the real Homebrew. It runs on Linux CI as well.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SCRIPT = "system/update-brew.py"

PREVIEWS = [
    "upgrade --dry-run",
    "upgrade --cask --dry-run",
    "autoremove --dry-run",
    "cleanup -s --dry-run",
]


@pytest.fixture
def brew(tmp_path, fake_bin) -> Path:
    """A fake ``brew`` that exits 1 when its subcommand is ``$FAKE_FAIL``.

    Returns the file the calls land in.
    """
    record = tmp_path / "brew.calls"
    fake_bin("brew", f'echo "$*" >> "{record}"\n[ "$1" = "${{FAKE_FAIL:-}}" ] && exit 1\nexit 0\n')
    return record


def calls(record: Path) -> list[str]:
    return record.read_text().splitlines() if record.exists() else []


def test_dry_run_only_previews_and_never_updates(brew, run_script):
    result = run_script(SCRIPT, ["--dry-run"], check=True)

    assert calls(brew) == PREVIEWS
    assert "  🪄 Would run: brew update" in result.stdout
    assert "update-brew 🌵 (dry run)" in result.stdout


def test_real_run(brew, run_script):
    result = run_script(SCRIPT, [], check=True)

    assert calls(brew) == ["update", "upgrade", "upgrade --cask", "autoremove", "cleanup -s"]
    assert "  ▶ brew update" in result.stdout


def test_no_cask_skips_the_cask_upgrade(brew, run_script):
    result = run_script(SCRIPT, ["--dry-run", "--no-cask"], check=True)

    assert calls(brew) == [call for call in PREVIEWS if "--cask" not in call]
    assert "⏭️  Skipping cask upgrades (--no-cask)" in result.stdout


def test_greedy_reaches_the_cask_upgrade(brew, run_script):
    run_script(SCRIPT, ["--dry-run", "--greedy"], check=True)

    assert "upgrade --cask --greedy --dry-run" in calls(brew)


def test_skipping_autoremove_and_cleanup(brew, run_script):
    run_script(SCRIPT, ["--no-autoremove", "--no-cleanup"], check=True)

    assert calls(brew) == ["update", "upgrade", "upgrade --cask"]


@pytest.mark.parametrize("flag", ["--no-cask=false", "--no-cleanup=true", "--no-autoremove=no"])
def test_inverted_flags_take_no_value(brew, run_script, flag):
    """`--no-cask=false` is a double negative; the shell version took the bare flag only."""
    result = run_script(SCRIPT, [flag])

    assert result.returncode == 1
    assert calls(brew) == []


def test_a_failing_real_step_is_fatal(brew, run_script):
    result = run_script(SCRIPT, [], env={"FAKE_FAIL": "upgrade"})

    assert result.returncode == 1
    assert calls(brew) == ["update", "upgrade"]


def test_a_failing_preview_is_not(brew, run_script):
    """brew's own --dry-run exits non-zero for things that are not failures."""
    run_script(SCRIPT, ["--dry-run"], env={"FAKE_FAIL": "upgrade"}, check=True)

    assert calls(brew) == PREVIEWS


def test_doctor_is_advisory(brew, run_script):
    result = run_script(SCRIPT, ["--doctor"], env={"FAKE_FAIL": "doctor"}, check=True)

    assert calls(brew)[-1] == "doctor"
    assert "⚠️  brew doctor reported issues (non-fatal)" in result.stdout
