"""Tests for bin/nas.py and the scripts under bin/drives/.

The scripts are macOS-only in earnest - osascript, diskutil, /Volumes - so
nothing here mounts or unmounts anything. A fake ``osascript`` on PATH stands
in for AppleScript, and the subprocess cases stick to the paths that finish
before any real drive is touched, so the suite runs on Linux CI as well.
"""

from __future__ import annotations

from pathlib import Path

import nas
import pytest
from conftest import load_script

EJECT = "drives/eject-all-drives.py"
MOUNT = "drives/mount-all-drives.py"
PING = "drives/ping-nas.py"

mount_all_drives = load_script(MOUNT)
ping_nas = load_script(PING)


@pytest.fixture
def osascript(tmp_path, fake_bin) -> Path:
    """A fake ``osascript`` first on PATH. Returns the file its argv lands in.

    It exits ``$FAKE_STATUS`` (default 0) after writing ``$FAKE_STDERR``.
    """
    record = tmp_path / "osascript.argv"
    fake_bin(
        "osascript",
        f'printf "%s\\n" "$@" >> "{record}"\n'
        'printf "%s" "${FAKE_STDERR:-}" >&2\n'
        'exit "${FAKE_STATUS:-0}"\n',
    )
    return record


@pytest.fixture
def failing_osascript(osascript, monkeypatch) -> Path:
    monkeypatch.setenv("FAKE_STATUS", "1")
    return osascript


# ---------------------------------------------------------------------------
# nas.py
# ---------------------------------------------------------------------------


def test_select_drives_without_only_is_every_drive():
    assert nas.select_drives("") == list(nas.NAS_DRIVES)


@pytest.mark.parametrize("only", ["Meleys", "meleys", "MELEYS"])
def test_select_drives_matches_case_insensitively(only):
    assert nas.select_drives(only) == [("Meleys", "192.168.50.2")]


@pytest.mark.parametrize("only", ["nope", "Mele", "Meleys-1", "192.168.50.2"])
def test_select_drives_unknown_name_selects_nothing(only):
    assert nas.select_drives(only) == []


def test_smb_url():
    assert nas.smb_url("Meleys", "192.168.50.2") == "smb://crivas@192.168.50.2/Meleys"


def test_mount_smb_runs_applescript_mount_volume(osascript, no_color, capsys):
    assert nas.mount_smb("Meleys", "Meleys") is True

    assert osascript.read_text().splitlines() == ["-e", 'mount volume "smb://crivas@Meleys/Meleys"']
    assert capsys.readouterr().out == ""


def test_mount_smb_failure_says_why(failing_osascript, no_color, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_STDERR", "execution error: no route (-5014)")

    assert nas.mount_smb("Meleys", "192.168.50.2") is False

    assert capsys.readouterr().out == (
        "  ❌ mount failed for smb://crivas@192.168.50.2/Meleys\n"
        "     execution error: no route (-5014)\n"
        "     Check that Keychain has a password for 'crivas@192.168.50.2'.\n"
    )


# ---------------------------------------------------------------------------
# mount-all-drives / ping-nas: their own lines around mount_smb
# ---------------------------------------------------------------------------


def test_mount_drive_output(osascript, no_color, capsys, monkeypatch):
    monkeypatch.setattr(mount_all_drives, "is_mounted", lambda name: False)

    assert mount_all_drives.mount_drive("Meleys", "192.168.50.2", quiet=False) == "mounted"

    assert capsys.readouterr().out == (
        "🔗 Mounting Meleys (smb://crivas@192.168.50.2/Meleys)...\n  ✅ Meleys mounted 🐉\n"
    )


def test_mount_drive_skips_a_mounted_drive(osascript, no_color, capsys, monkeypatch):
    monkeypatch.setattr(mount_all_drives, "is_mounted", lambda name: True)

    assert mount_all_drives.mount_drive("Meleys", "Meleys", quiet=False) == "skipped"

    assert capsys.readouterr().out == "⏭️  Meleys — already mounted\n"
    assert not osascript.exists()


def test_remount_drive_output(failing_osascript, no_color, capsys):
    assert ping_nas.remount_drive("Vhagar", "Vhagar") is False

    assert capsys.readouterr().out == (
        "  🔗 Remounting Vhagar (smb://crivas@Vhagar/Vhagar)...\n"
        "  ❌ mount failed for smb://crivas@Vhagar/Vhagar\n"
        "     Check that Keychain has a password for 'crivas@Vhagar'.\n"
    )


# ---------------------------------------------------------------------------
# An --only that names no drive: each script keeps its own reaction
# ---------------------------------------------------------------------------


def test_eject_unknown_only_warns_and_exits_zero(run_script):
    """The shell version printed a 0/0 summary and exited 0; a dry run needs no diskutil."""
    result = run_script(EJECT, ["--dry-run", "--only=nope"])

    assert result.returncode == 0
    assert "⚠️  No drive named 'nope'. Known: Meleys, Vermithor, Caraxes" in result.stdout
    assert "🌵 Would eject:  0" in result.stdout


def test_mount_unknown_only_warns_and_exits_zero(osascript, run_script):
    result = run_script(MOUNT, ["--only=nope"])

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "═" * 43,
        "💿  mount-all-drives",
        "═" * 43,
        "⚠️  No drive named 'nope'. Known: Meleys, Vermithor, Caraxes, Syrax, Vhagar",
        "",
        "─" * 45,
        "✅ Mounted:  0",
        "⏭️  Skipped:  0 (already mounted)",
        "🎉 All drives are up! 🐉🐉🐉",
    ]
    assert not osascript.exists()


def test_ping_unknown_only_exits_one(run_script):
    result = run_script(PING, ["--only=nope", "--once"])

    assert result.returncode == 1
    assert result.stdout.strip() == "❌ No drives matched --only=nope"


@pytest.mark.parametrize(
    ("flag", "message"),
    [
        ("--interval=0", "❌ --interval must be a positive integer (got: 0)"),
        ("--interval=5s", "❌ --interval must be a positive integer (got: 5s)"),
        ("--ping-timeout=-1", "❌ --ping-timeout must be a positive integer (got: -1)"),
    ],
)
def test_ping_rejects_a_bad_count(run_script, flag, message):
    result = run_script(PING, [flag, "--once"])

    assert result.returncode == 1
    assert result.stdout.strip() == message


@pytest.mark.parametrize(
    ("script", "flag"),
    [
        (EJECT, "--no-force=false"),
        (EJECT, "--no-clear-favorites=true"),
        (PING, "--no-remount=false"),
    ],
)
def test_inverted_flags_take_no_value(run_script, script, flag):
    """`--no-force=false` would be a double negative; argv parsing refuses it."""
    result = run_script(script, [flag])

    assert result.returncode == 1
    assert f"❌ argument {flag.partition('=')[0]}: ignored explicit argument" in result.stdout
