"""``che doctor`` reports on the install without changing it."""

from __future__ import annotations

import json

import doctor
import install
import machine
import pytest
import shellgen
from commands import VERSION


@pytest.fixture
def installed(fake_home, no_regen, monkeypatch):
    """A zsh install into the fake HOME, without regenerating the repo's files."""
    monkeypatch.setenv("SHELL", "/bin/zsh")
    install.perform_install(install.InstallPlan(shells=["zsh"], python=machine.find_python()[0]))
    return fake_home / ".zshrc"


def checks() -> dict[str, doctor.Check]:
    return {check.name: check for check in doctor.diagnose()}


def test_doctor_reports_a_missing_install(fake_home, monkeypatch):
    # diagnose() watches only the login shell's rc files when nothing is
    # installed yet, so pin SHELL or the zsh: check disappears on CI (bash).
    monkeypatch.setenv("SHELL", "/bin/zsh")
    found = checks()
    assert found["install record"].status == doctor.FAIL
    assert found["zsh: ~/.zshrc"].status == doctor.FAIL


def test_a_config_that_is_not_an_object_reads_as_no_install(fake_home, monkeypatch):
    """It used to crash diagnose() on `.get`."""
    monkeypatch.setenv("SHELL", "/bin/zsh")
    machine.config_file().parent.mkdir(parents=True)
    machine.config_file().write_text("[]\n")
    assert checks()["install record"].status == doctor.FAIL


def test_doctor_passes_after_installing(installed):
    found = checks()
    assert found["install record"].status == doctor.OK
    assert found["zsh: ~/.zshrc"].status == doctor.OK
    assert not any(check.status == doctor.FAIL for check in found.values())


def test_an_alias_shadowing_a_wrapper_is_a_warning_with_a_fix(installed):
    installed.write_text('alias remove-metadata="exiftool -all= "\n' + installed.read_text())
    check = checks()["zsh: ~/.zshrc"]
    assert check.status == doctor.WARN
    assert "remove-metadata (alias)" in check.detail
    assert check.fix == doctor.ALIAS_FIX


def test_an_unreadable_rc_file_fails_its_own_check_only(installed):
    installed.unlink()
    installed.mkdir()
    found = checks()
    assert found["zsh: ~/.zshrc"].status == doctor.FAIL
    assert found["zsh: ~/.zshrc"].detail.startswith("unreadable (")
    assert found["install record"].status == doctor.OK


def test_a_readme_without_its_markers_is_a_warning_not_a_crash(fake_home, monkeypatch):
    def broken(*, dry_run):
        raise ValueError("README.md is missing the markers")

    monkeypatch.setattr(shellgen, "sync_generated", broken)
    check = checks()["generated files"]
    assert check.status == doctor.WARN
    assert "markers" in check.detail


def test_json_keeps_its_shape(installed, capsys):
    assert doctor.doctor_main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == VERSION
    assert all(list(check) == ["name", "status", "detail", "fix"] for check in payload["checks"])


def test_present_tools_are_listed_only_when_verbose(installed, monkeypatch, capsys):
    monkeypatch.setenv("NO_COLOR", "1")
    doctor.doctor_main([])
    quiet = capsys.readouterr().out
    doctor.doctor_main(["--verbose"])
    verbose = capsys.readouterr().out

    present = [
        check.name for check in doctor.diagnose() if check.quiet and check.status == doctor.OK
    ]
    for name in present:
        assert name not in quiet
        assert name in verbose
