"""The installer edits the user's dotfiles, so the tests hold it to that bar.

Every case runs against a temporary HOME. ``bin/install.py`` resolves every
path from the environment at call time precisely so this is possible - nothing
is captured at import time.
"""

from __future__ import annotations

import json
import os
import stat

import install
import pytest
import shellgen

LEGACY_RC = """\
# my own settings
export EDITOR=nvim
alias ll="ls -la"

# -----------------------------------------------------------------------------
# Shell functions (single source of truth)
# -----------------------------------------------------------------------------

SHELL_FUNCTIONS_BIN="${HOME}/Developer/git/shell-functions/bin"

# Delete local branches whose upstream is gone
clean-stale-branches() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/git/clean-stale-branches.py"
  playsound-4
}

show-codecs() {
  python3 "${SHELL_FUNCTIONS_BIN}/video/show-codecs.py" "$@"
  playsound-6
}

# something of the user's own that must survive
my-helper() {
  echo "mine"
}

export PATH="$HOME/bin:$PATH"
"""


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("ZDOTDIR", raising=False)
    return home


# ---------------------------------------------------------------------------
# Block management
# ---------------------------------------------------------------------------


def test_apply_block_creates_then_leaves_alone(fake_home):
    rc = fake_home / ".zshrc"
    block = shellgen.rc_block("zsh", home=fake_home, python="python3")

    assert install.apply_block(rc, block) == "created"
    assert shellgen.BEGIN_MARKER in rc.read_text()
    assert install.apply_block(rc, block) == "unchanged"


def test_apply_block_preserves_the_rest_of_the_file(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text("# top\nexport EDITOR=nvim\n")
    install.apply_block(rc, shellgen.rc_block("zsh", home=fake_home, python="python3"))

    text = rc.read_text()
    assert "export EDITOR=nvim" in text
    assert text.index("export EDITOR") < text.index(shellgen.BEGIN_MARKER)


def test_apply_block_replaces_in_place_without_moving_it(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text("# before\n")
    install.apply_block(rc, shellgen.rc_block("zsh", home=fake_home, python="python3"))
    rc.write_text(rc.read_text() + "\n# after the block\n")

    assert (
        install.apply_block(rc, shellgen.rc_block("zsh", home=fake_home, python="/new/python"))
        == "updated"
    )
    text = rc.read_text()
    assert "/new/python" in text
    assert text.count(shellgen.BEGIN_MARKER) == 1
    assert text.strip().endswith("# after the block")


def test_apply_block_backs_the_file_up_first(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text("# original\n")
    install.apply_block(rc, shellgen.rc_block("zsh", home=fake_home, python="python3"))

    backups = list(install.backup_dir().glob("zshrc.*.bak"))
    assert backups, "no backup was written"
    assert backups[0].read_text() == "# original\n"


def test_apply_block_survives_a_deleted_end_marker(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text(f"# top\n{shellgen.BEGIN_MARKER}\nexport CHE_HOME=/old\n")
    install.apply_block(rc, shellgen.rc_block("zsh", home=fake_home, python="python3"))

    text = rc.read_text()
    assert text.count(shellgen.BEGIN_MARKER) == 1
    assert "/old" not in text


def test_remove_block_leaves_the_file_as_it_was(fake_home):
    rc = fake_home / ".zshrc"
    original = "# top\nexport EDITOR=nvim\n"
    rc.write_text(original)
    install.apply_block(rc, shellgen.rc_block("zsh", home=fake_home, python="python3"))

    assert install.remove_block(rc) is True
    assert rc.read_text().strip() == original.strip()
    assert install.remove_block(rc) is False


def test_dry_run_touches_nothing(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text("# untouched\n")
    block = shellgen.rc_block("zsh", home=fake_home, python="python3")

    assert install.apply_block(rc, block, dry_run=True) == "created"
    assert rc.read_text() == "# untouched\n"


# ---------------------------------------------------------------------------
# Legacy wrappers
# ---------------------------------------------------------------------------


def test_find_legacy_names_the_hand_written_wrappers(fake_home):
    names = install.find_legacy(LEGACY_RC)
    assert "clean-stale-branches" in names
    assert "show-codecs" in names
    assert "my-helper" not in names


def test_strip_legacy_keeps_everything_else(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text(LEGACY_RC)

    removed = install.strip_legacy(rc)
    text = rc.read_text()

    assert set(removed) == {"clean-stale-branches", "show-codecs"}
    assert "my-helper()" in text
    assert 'export PATH="$HOME/bin:$PATH"' in text
    assert "export EDITOR=nvim" in text
    assert "SHELL_FUNCTIONS_BIN" not in text
    # The comment that documented a removed wrapper goes with it.
    assert "Delete local branches whose upstream is gone" not in text


def test_strip_legacy_ignores_the_managed_block(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text(LEGACY_RC)
    install.apply_block(rc, shellgen.rc_block("zsh", home=fake_home, python="python3"))

    install.strip_legacy(rc)
    text = rc.read_text()
    assert shellgen.BEGIN_MARKER in text
    assert "SHELL_FUNCTIONS_BIN=" not in text.split(shellgen.BEGIN_MARKER)[0]


TABLE_RC = """\
# my own settings
alias ll="ls -la"

SHELL_FUNCTIONS_BIN="${HOME}/Developer/git/shell-functions/bin"

_sf_run() {
  python3 "${SHELL_FUNCTIONS_BIN}/$1" "${@:2}"
}

# _sf <fn-name> <relative-script> <sound>
_sf() {
  functions[$1]="_sf_run $2"
}

# Git ---
_sf show-codecs   video/show-codecs.py   6
_sf delete-by-ext files/delete-by-ext.py 6

# The user's own automation, which must survive.
morning() {
  sync-all-branches
  mount-all-drives
}
"""


def test_strip_legacy_removes_a_table_and_its_helpers(fake_home):
    """A helper that builds wrappers is legacy too, and so are its call lines:
    deleting `_sf_run` but leaving forty `_sf …` lines would greet every new
    shell with forty "command not found" errors."""
    rc = fake_home / ".zshrc"
    rc.write_text(TABLE_RC)

    removed = install.strip_legacy(rc)
    text = rc.read_text()

    assert {"_sf", "_sf_run"} <= set(removed)
    assert "_sf" not in text
    assert "SHELL_FUNCTIONS_BIN" not in text
    assert 'alias ll="ls -la"' in text


def test_strip_legacy_keeps_the_users_own_automation(fake_home):
    """`morning` calls a wrapper but is not one, so growth must stop there."""
    rc = fake_home / ".zshrc"
    rc.write_text(TABLE_RC)
    install.strip_legacy(rc)

    text = rc.read_text()
    assert "morning() {" in text
    assert "  sync-all-branches" in text
    assert "  mount-all-drives" in text


def test_strip_legacy_is_a_no_op_on_a_clean_file(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text("# nothing to see\n")
    assert install.strip_legacy(rc) == []
    assert rc.read_text() == "# nothing to see\n"


def test_find_shadowing_catches_an_alias(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text('alias remove-metadata="exiftool -all= "\n')
    install.apply_block(rc, shellgen.rc_block("zsh", home=fake_home, python="python3"))

    assert ("remove-metadata", "alias") in install.find_shadowing(rc.read_text())


def test_find_shadowing_catches_a_later_redefinition(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text("show-codecs() { echo mine; }\n")
    install.apply_block(rc, shellgen.rc_block("zsh", home=fake_home, python="python3"))
    rc.write_text(rc.read_text() + "\nvideo-list() { echo mine; }\n")

    shadowed = dict(install.find_shadowing(rc.read_text()))
    # Defined before the block, so the generated wrapper still wins.
    assert "show-codecs" not in shadowed
    assert shadowed["video-list"] == "redefined after the block"


def test_find_shadowing_ignores_unrelated_names(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text("alias ll='ls -la'\nmy-helper() { echo hi; }\n")
    install.apply_block(rc, shellgen.rc_block("zsh", home=fake_home, python="python3"))
    assert install.find_shadowing(rc.read_text()) == []


# ---------------------------------------------------------------------------
# Shell detection
# ---------------------------------------------------------------------------


def test_zsh_target_follows_zdotdir(fake_home, monkeypatch):
    monkeypatch.setenv("ZDOTDIR", str(fake_home / "config" / "zsh"))
    zsh = next(target for target in install.detect_shells() if target.name == "zsh")
    assert zsh.rc_files == [fake_home / "config" / "zsh" / ".zshrc"]


def test_bash_targets_every_rc_that_exists(fake_home):
    (fake_home / ".bashrc").write_text("")
    (fake_home / ".bash_profile").write_text("")
    files = install._bash_rc_files()
    assert files == [fake_home / ".bashrc", fake_home / ".bash_profile"]


def test_bash_falls_back_to_bashrc(fake_home):
    assert install._bash_rc_files() == [fake_home / ".bashrc"]


def test_default_selection_always_includes_the_login_shell(fake_home, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/bash")
    assert "bash" in install.default_shell_selection(install.detect_shells())


def test_default_selection_never_writes_to_profile(fake_home, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    (fake_home / ".profile").write_text("")
    assert "sh" not in install.default_shell_selection(install.detect_shells())


# ---------------------------------------------------------------------------
# Shim, config, install
# ---------------------------------------------------------------------------


def test_shim_is_executable_and_runs_che(fake_home):
    assert install.install_shim("/usr/bin/python3") == "installed"
    shim = install.shim_path()
    assert shim.stat().st_mode & stat.S_IXUSR
    assert "bin/che.py" in shim.read_text()
    assert install.install_shim("/usr/bin/python3") == "unchanged"


def test_perform_install_records_what_it_did(fake_home, monkeypatch):
    monkeypatch.setattr(install, "write_generated", lambda dry_run=False: [])

    plan = install.InstallPlan(shells=["zsh"], python="/usr/bin/python3")
    result = install.perform_install(plan)

    assert result.rc_actions == [(fake_home / ".zshrc", "created")]
    config = json.loads(install.config_file().read_text())
    assert config["shells"] == ["zsh"]
    assert config["python"] == "/usr/bin/python3"
    assert config["version"] == install.VERSION


def test_perform_install_dry_run_writes_nothing(fake_home, monkeypatch):
    monkeypatch.setattr(install, "write_generated", lambda dry_run=False: [])

    plan = install.InstallPlan(shells=["zsh"], python="python3", dry_run=True)
    install.perform_install(plan)

    assert not (fake_home / ".zshrc").exists()
    assert not install.config_file().exists()
    assert not install.shim_path().exists()


def test_generated_files_in_the_repo_are_current():
    """`che install` regenerates shell/; this is the check CI runs."""
    assert install.check_generated() == [], "run `bun run generate` and commit the result"


def test_doctor_reports_a_missing_install(fake_home, monkeypatch, capsys):
    # diagnose() watches only the login shell's rc files when nothing is
    # installed yet, so pin SHELL or the zsh: check disappears on CI (bash).
    monkeypatch.setenv("SHELL", "/bin/zsh")
    checks = {check["name"]: check for check in install.diagnose()}
    assert checks["install record"]["status"] == install.FAIL
    assert any(name.startswith("zsh:") for name in checks)


def test_doctor_passes_after_installing(fake_home, monkeypatch):
    monkeypatch.setattr(install, "write_generated", lambda dry_run=False: [])
    monkeypatch.setenv("SHELL", "/bin/zsh")
    install.perform_install(install.InstallPlan(shells=["zsh"], python=install.find_python()[0]))

    checks = {check["name"]: check for check in install.diagnose()}
    assert checks["install record"]["status"] == install.OK
    assert (
        checks[f"zsh: {install.home()}/.zshrc".replace(str(install.home()), "~")]["status"]
        == install.OK
    )
    assert not any(check["status"] == install.FAIL for check in checks.values())


def test_uninstall_removes_everything_it_made(fake_home, monkeypatch, capsys):
    monkeypatch.setattr(install, "write_generated", lambda dry_run=False: [])
    install.perform_install(install.InstallPlan(shells=["zsh"], python="python3"))

    assert install.uninstall(purge=True) == 0
    assert shellgen.BEGIN_MARKER not in (fake_home / ".zshrc").read_text()
    assert not install.shim_path().exists()
    assert not install.config_dir().exists()


def test_install_main_rejects_an_unknown_shell(fake_home):
    with pytest.raises(SystemExit) as exit_info:
        install.install_main(["--shells=powershell", "--yes"])
    assert exit_info.value.code == 1


def test_install_main_check_mode_passes(fake_home, capsys):
    assert install.install_main(["--check"]) == 0


def test_python_detection_prefers_a_new_enough_interpreter():
    executable, version = install.find_python()
    assert version is not None
    assert version[:2] >= install.MIN_PYTHON
    assert os.access(executable, os.X_OK)
