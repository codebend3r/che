"""Machine facts: which shells exist, which python runs the scripts, where che came from."""

from __future__ import annotations

import json
import os
import shutil

import machine
import pytest


def rc_files(shell: str) -> list:
    return machine.SHELLS[shell].rc_files


# ---------------------------------------------------------------------------
# Shells
# ---------------------------------------------------------------------------


def test_zsh_target_follows_zdotdir(fake_home, monkeypatch):
    monkeypatch.setenv("ZDOTDIR", str(fake_home / "config" / "zsh"))
    assert rc_files("zsh") == [fake_home / "config" / "zsh" / ".zshrc"]


def test_bash_targets_every_rc_that_exists(fake_home):
    (fake_home / ".bashrc").write_text("")
    (fake_home / ".bash_profile").write_text("")
    assert rc_files("bash") == [fake_home / ".bashrc", fake_home / ".bash_profile"]


def test_bash_falls_back_to_bashrc(fake_home):
    assert rc_files("bash") == [fake_home / ".bashrc"]


def test_fish_follows_xdg_config_home(fake_home, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_home / "xdg"))
    assert rc_files("fish") == [fake_home / "xdg" / "fish" / "config.fish"]
    assert machine.config_dir() == fake_home / "xdg" / "che"


def test_sh_is_opt_in_and_shares_the_bash_wrappers(fake_home):
    sh = machine.SHELLS["sh"]
    assert sh.opt_in
    assert sh.flavor == "bash"
    assert not any(spec.opt_in for name, spec in machine.SHELLS.items() if name != "sh")


def test_default_selection_always_includes_the_login_shell(fake_home, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/bash")
    assert "bash" in machine.default_shell_selection()


def test_default_selection_never_writes_to_profile(fake_home, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/sh")
    (fake_home / ".profile").write_text("")
    assert "sh" not in machine.default_shell_selection()


# ---------------------------------------------------------------------------
# The install record
# ---------------------------------------------------------------------------


def write_config(text: str) -> None:
    machine.config_file().parent.mkdir(parents=True, exist_ok=True)
    machine.config_file().write_text(text)


def test_a_record_round_trips(fake_home):
    record = machine.InstallRecord(version="1.0.0", shells=["fish"], sounds=False)
    machine.save_record(record)
    assert machine.load_record() == record


def test_an_empty_recorded_shell_list_falls_back_to_the_defaults(fake_home, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    write_config(json.dumps({"version": "1.0.0", "shells": []}))
    assert machine.load_record().shells == machine.default_shell_selection()


def test_an_older_records_extra_keys_are_ignored(fake_home):
    write_config(json.dumps({"version": "1.0.0", "shells": ["zsh"], "completions": True}))
    record = machine.load_record()
    assert (record.version, record.shells, record.sounds) == ("1.0.0", ["zsh"], True)


@pytest.mark.parametrize("text", [None, "", "not json", "[]", "{}", '"zsh"'])
def test_anything_but_a_json_object_is_no_record(fake_home, text):
    if text is not None:
        write_config(text)
    assert machine.load_record() is None


def test_tildify_only_shortens_paths_under_home(fake_home):
    assert machine.tildify(fake_home / ".zshrc") == "~/.zshrc"
    sibling = fake_home.parent / f"{fake_home.name}-other" / ".zshrc"
    assert machine.tildify(sibling) == str(sibling)


# ---------------------------------------------------------------------------
# Python and tools
# ---------------------------------------------------------------------------


def test_python_detection_prefers_a_new_enough_interpreter():
    executable, version = machine.find_python()
    assert machine.python_ok(version)
    assert os.access(executable, os.X_OK)


def test_python_version_helpers():
    assert machine.MIN_PYTHON_TEXT == "3.12"
    assert machine.version_text((3, 13, 1)) == "3.13.1"
    assert machine.python_ok((3, 12, 0))
    assert not machine.python_ok((3, 9, 6))


def test_install_hints_name_the_brew_formula():
    assert machine.INSTALL_HINTS["ffprobe"] == "brew install ffmpeg"
    for binary, formula in machine.BREW_FORMULA.items():
        assert machine.INSTALL_HINTS[binary] == f"brew install {formula}"
    assert "brew" not in machine.BREW_FORMULA
    assert "curl" in machine.INSTALL_HINTS["brew"]


def test_missing_binaries_skips_what_macos_ships(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _binary: None)
    missing = machine.missing_binaries()
    assert missing == sorted(missing)
    assert "ffprobe" in missing
    assert not set(missing) & machine.SYSTEM_BINARIES


# ---------------------------------------------------------------------------
# Install source
# ---------------------------------------------------------------------------


def test_update_command_matches_the_checkout_kind(fake_home, monkeypatch, tmp_path):
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    monkeypatch.setattr(machine, "REPO", clone)
    assert machine.is_git_checkout()
    assert machine.update_command() == "git pull"

    package = tmp_path / "node_modules" / "@codebend3r" / "che"
    package.mkdir(parents=True)
    monkeypatch.setattr(machine, "REPO", package)
    assert not machine.is_git_checkout()
    assert machine.update_command().startswith("npm install -g ")
