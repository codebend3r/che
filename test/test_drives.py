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
from conftest import load_script, summary
from report import Tally

EJECT = "drives/eject-all-drives.py"
MOUNT = "drives/mount-all-drives.py"
PING = "drives/ping-nas.py"

DRIVE = nas.NasDrive("Vhagar", "192.168.50.5")

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


@pytest.fixture(autouse=True)
def names_resolve(monkeypatch):
    """Drive names resolve, so URLs use them; the fallback tests override this."""
    monkeypatch.setattr(nas, "resolves", lambda host: True)


def test_select_drives_without_only_is_every_drive():
    assert nas.select_drives("") == list(nas.NAS_DRIVES)


@pytest.mark.parametrize("only", ["Meleys", "meleys", "MELEYS"])
def test_select_drives_matches_case_insensitively(only):
    assert nas.select_drives(only) == [nas.NasDrive("Meleys", "192.168.50.2")]


@pytest.mark.parametrize("only", ["nope", "Mele", "Meleys-1", "192.168.50.2"])
def test_select_drives_unknown_name_selects_nothing(only):
    assert nas.select_drives(only) == []


def test_url_reaches_the_drive_by_name_or_by_ip():
    meleys = nas.NasDrive("Meleys", "192.168.50.2")

    assert meleys.url(use_ip=False) == "smb://crivas@Meleys/Meleys"
    assert meleys.url(use_ip=True) == "smb://crivas@192.168.50.2/Meleys"


def test_balerion_mounts_the_share_named_after_it():
    """Its old Media share is gone; the box now shares a folder called Balerion."""
    (balerion,) = nas.select_drives("balerion")

    assert balerion.url(use_ip=True) == "smb://crivas@192.168.50.234/Balerion"


def test_mount_smb_runs_applescript_mount_volume(osascript, no_color, capsys):
    assert nas.mount_smb("smb://crivas@Meleys/Meleys") == ""

    assert osascript.read_text().splitlines() == ["-e", 'mount volume "smb://crivas@Meleys/Meleys"']
    assert capsys.readouterr().out == ""


def test_mount_smb_failure_says_why(failing_osascript, no_color, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_STDERR", "execution error: no route (-5014)")

    url = "smb://crivas@192.168.50.2/Meleys"

    assert nas.mount_smb(url) == "execution error: no route (-5014)"
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# mount-all-drives / ping-nas: their own lines around mount_smb
# ---------------------------------------------------------------------------


def test_mount_drive_records_a_mount(osascript, no_color, capsys, monkeypatch):
    monkeypatch.setattr(mount_all_drives, "is_mounted", lambda name: False)
    tally = Tally(mount_all_drives.Mount)

    mount_all_drives.mount_drive(tally, nas.NasDrive("Meleys", "192.168.50.2"), use_ip=True)

    assert tally.names(mount_all_drives.Mount.MOUNTED) == ["Meleys"]
    assert capsys.readouterr().out == (
        "\n  ✓ mounted       Meleys  smb://crivas@192.168.50.2/Meleys\n"
    )


def test_mount_drive_counts_a_mounted_drive_silently(osascript, no_color, capsys, monkeypatch):
    monkeypatch.setattr(mount_all_drives, "is_mounted", lambda name: True)
    tally = Tally(mount_all_drives.Mount)

    mount_all_drives.mount_drive(tally, nas.NasDrive("Meleys", "192.168.50.2"), use_ip=False)

    assert tally.names(mount_all_drives.Mount.ALREADY) == ["Meleys"]
    assert capsys.readouterr().out == ""
    assert not osascript.exists()


def test_mount_drive_folds_the_failure_into_one_line(
    failing_osascript, no_color, capsys, monkeypatch
):
    monkeypatch.setattr(mount_all_drives, "is_mounted", lambda name: False)
    monkeypatch.setenv("FAKE_STDERR", "execution error: no route (-5014)")
    tally = Tally(mount_all_drives.Mount)

    mount_all_drives.mount_drive(tally, DRIVE, use_ip=False)

    assert capsys.readouterr().out == (
        "\n  ✗ failed        Vhagar  "
        "smb://crivas@Vhagar/Vhagar: execution error: no route (-5014)\n"
    )
    assert [e.item for e in tally.results[mount_all_drives.Mount.FAILED]] == [
        "Vhagar: execution error: no route (-5014)"
    ]


@pytest.mark.parametrize(
    ("reachable", "mounted", "remount", "outcome"),
    [
        (False, False, True, "UNREACHABLE"),
        (True, True, True, "MOUNTED"),
        (True, False, False, "NOT_MOUNTED"),
        (True, False, True, "REMOUNTED"),
    ],
)
def test_check_drive_outcomes(
    osascript, no_color, monkeypatch, reachable, mounted, remount, outcome
):
    monkeypatch.setattr(ping_nas, "smb_reachable", lambda ip, timeout: reachable)
    monkeypatch.setattr(ping_nas, "is_mounted", lambda name: mounted)
    tally = Tally(ping_nas.Ping)

    ping_nas.check_drive(tally, DRIVE, ping_timeout=1, remount=remount, use_ip=False)

    assert tally.names(ping_nas.Ping[outcome]) == ["Vhagar"]


def test_check_drive_remount_failure(failing_osascript, no_color, capsys, monkeypatch):
    monkeypatch.setattr(ping_nas, "smb_reachable", lambda ip, timeout: True)
    monkeypatch.setattr(ping_nas, "is_mounted", lambda name: False)
    tally = Tally(ping_nas.Ping)

    ping_nas.check_drive(tally, DRIVE, ping_timeout=1, remount=True, use_ip=False)

    assert capsys.readouterr().out == (
        "\n  ✗ failed        Vhagar  smb://crivas@Vhagar/Vhagar: mount volume failed\n"
    )


def test_ping_cycle_summary(osascript, no_color, capsys, monkeypatch):
    monkeypatch.setattr(ping_nas, "smb_reachable", lambda ip, timeout: ip != "192.168.50.2")
    monkeypatch.setattr(ping_nas, "is_mounted", lambda name: name != "Vermithor")
    active = nas.select_drives("")

    ping_nas.ping_all_nas(active, cycle=1, ping_timeout=1, remount=True, use_ip=False, quiet=False)

    rows = summary(capsys.readouterr().out)
    assert rows["Remounted"] == ["Vermithor"]
    assert rows["Unreachable"] == ["Meleys: SMB port 445 unreachable at 192.168.50.2"]
    assert rows["Mounted"] == []


def test_ping_quiet_cycle_with_everything_fine_prints_nothing(no_color, capsys, monkeypatch):
    monkeypatch.setattr(ping_nas, "smb_reachable", lambda ip, timeout: True)
    monkeypatch.setattr(ping_nas, "is_mounted", lambda name: True)

    ping_nas.ping_all_nas(
        nas.select_drives(""), cycle=1, ping_timeout=1, remount=True, use_ip=False, quiet=True
    )

    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# An --only that names no drive: each script keeps its own reaction
# ---------------------------------------------------------------------------


def test_eject_unknown_only_warns_and_exits_zero(run_script):
    """The shell version printed a 0/0 summary and exited 0; a dry run needs no diskutil."""
    result = run_script(EJECT, ["--dry-run", "--only=nope"])

    assert result.returncode == 0
    assert "⚠️  No drive named 'nope'. Known: Meleys, Vermithor, Caraxes" in result.stdout
    assert "\nPreview  0 drives" in result.stdout
    assert summary(result.stdout) == {}


def test_mount_unknown_only_warns_and_exits_zero(osascript, run_script):
    result = run_script(MOUNT, ["--only=nope"])

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "═" * 43,
        "💿  mount-all-drives",
        "═" * 43,
        "⚠️  No drive named 'nope'. Known: Meleys, Vermithor, Caraxes, Syrax, Vhagar, Balerion",
        "",
        "─" * 45,
        result.stdout.splitlines()[6],
        "",
        "🎉 All drives are up! 🐉🐉🐉",
    ]
    assert result.stdout.splitlines()[6].startswith("Summary  0 drives · ")
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


def test_mount_url_falls_back_to_ip_when_the_name_does_not_resolve(monkeypatch):
    monkeypatch.setattr(nas, "resolves", lambda host: False)
    (balerion,) = nas.select_drives("balerion")

    assert balerion.mount_url(use_ip=False) == "smb://crivas@192.168.50.234/Balerion"


def test_mount_url_keeps_the_name_when_it_resolves(monkeypatch):
    monkeypatch.setattr(nas, "resolves", lambda host: True)
    (balerion,) = nas.select_drives("balerion")

    assert balerion.mount_url(use_ip=False) == "smb://crivas@Balerion/Balerion"
