"""The install, update and uninstall workflows, end to end against a temporary HOME.

Every test that installs replaces ``shellgen.sync_generated`` so nothing is
written into the repo itself, and runs under ``fake_home`` so nothing is
written into the developer's own dotfiles.
"""

from __future__ import annotations

import stat
import sys

import install
import machine
import pytest
import rcfile
import shellgen
from commands import PACKAGE_NAME, VERSION
from conftest import git

LEGACY_RC = """\
export EDITOR=nvim

SHELL_FUNCTIONS_BIN="${HOME}/Developer/git/shell-functions/bin"

# Delete local branches whose upstream is gone
clean-stale-branches() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/git/clean-stale-branches.py"
  playsound-4
}
"""


@pytest.fixture
def fake_repo(monkeypatch):
    """Point both copies of REPO somewhere else: the one ``is_git_checkout``
    reads, and the one ``update`` runs git in."""

    def _point(path):
        monkeypatch.setattr(machine, "REPO", path)
        monkeypatch.setattr(install, "REPO", path)

    return _point


# ---------------------------------------------------------------------------
# Shim and install
# ---------------------------------------------------------------------------


def test_shim_is_executable_and_runs_che(fake_home):
    assert install.install_shim("/usr/bin/python3") == "installed"
    shim = machine.shim_path()
    assert shim.stat().st_mode & stat.S_IXUSR
    assert "bin/che.py" in shim.read_text()
    assert install.install_shim("/usr/bin/python3") == "unchanged"


def test_shim_never_writes_through_a_link_to_the_dispatcher(fake_home, fake_repo):
    """npm's global install can link ~/.local/bin/che to bin/che.py; writing
    through that link would replace the dispatcher with a shim that execs itself."""
    dispatcher = fake_home / "repo" / "bin" / "che.py"
    dispatcher.parent.mkdir(parents=True)
    dispatcher.write_text("# the dispatcher\n")
    shim = machine.shim_path()
    shim.parent.mkdir(parents=True)
    shim.symlink_to(dispatcher)
    fake_repo(fake_home / "repo")

    assert install.install_shim("/usr/bin/python3") == "unchanged"
    assert dispatcher.read_text() == "# the dispatcher\n"

    assert install.uninstall() == 0
    assert shim.is_symlink()


def test_shim_replaces_a_link_to_anything_else(fake_home):
    elsewhere = fake_home / "elsewhere"
    elsewhere.write_text("# not che\n")
    shim = machine.shim_path()
    shim.parent.mkdir(parents=True)
    shim.symlink_to(elsewhere)

    assert install.install_shim("/usr/bin/python3") == "installed"
    assert not shim.is_symlink()
    assert install.is_che_shim(shim)
    assert elsewhere.read_text() == "# not che\n"


def test_perform_install_records_what_it_did(fake_home, no_regen):
    plan = install.InstallPlan(shells=["zsh"], python="/usr/bin/python3")
    result = install.perform_install(plan)

    assert result.rc_actions == [(fake_home / ".zshrc", "created")]
    record = machine.load_record()
    assert record is not None
    assert record.shells == ["zsh"]
    assert record.python == "/usr/bin/python3"
    assert record.version == VERSION
    assert record.rc_files == [str(fake_home / ".zshrc")]


def test_a_recorded_install_repeats_itself(fake_home, no_regen):
    plan = install.InstallPlan(shells=["zsh"], python="python3", sounds=False, path_shim=False)
    install.perform_install(plan)

    again = install.InstallPlan.from_record(machine.load_record(), python="python3", dry_run=False)
    assert (again.shells, again.sounds, again.path_shim) == (["zsh"], False, False)


def test_perform_install_dry_run_writes_nothing(fake_home, no_regen):
    plan = install.InstallPlan(shells=["zsh"], python="python3", dry_run=True)
    install.perform_install(plan)

    assert not (fake_home / ".zshrc").exists()
    assert not machine.config_file().exists()
    assert not machine.shim_path().exists()


def test_replace_legacy_backs_up_the_original_file(fake_home, no_regen):
    """Stripping and adding the block used to be two writes and two backups in
    the same second; the second backup, already stripped, replaced the first."""
    rc = fake_home / ".zshrc"
    rc.write_text(LEGACY_RC)

    plan = install.InstallPlan(shells=["zsh"], python="python3", replace_legacy=True)
    result = install.perform_install(plan)

    assert result.legacy_removed == {rc: ["clean-stale-branches"]}
    backups = list(machine.backup_dir().glob("zshrc.*.bak"))
    assert [backup.read_text() for backup in backups] == [LEGACY_RC]
    assert "SHELL_FUNCTIONS_BIN" not in rc.read_text()
    assert shellgen.BEGIN_MARKER in rc.read_text()


def test_a_symlinked_rc_file_stays_a_symlink(fake_home, no_regen):
    dotfiles = fake_home / "dotfiles"
    dotfiles.mkdir()
    (dotfiles / "zshrc").write_text("# mine\n")
    (fake_home / ".zshrc").symlink_to(dotfiles / "zshrc")

    install.perform_install(install.InstallPlan(shells=["zsh"], python="python3"))

    assert (fake_home / ".zshrc").is_symlink()
    assert shellgen.BEGIN_MARKER in (dotfiles / "zshrc").read_text()


@pytest.mark.parametrize("path_shim", [True, False])
def test_print_shows_exactly_the_block_an_install_writes(fake_home, no_regen, capsys, path_shim):
    flags = [] if path_shim else ["--no-path-shim"]
    assert install.install_main(["--print", "--shells=zsh", "--no-sounds", *flags]) == 0
    printed = capsys.readouterr().out

    python = machine.find_python()[0]
    plan = install.InstallPlan(shells=["zsh"], python=python, sounds=False, path_shim=path_shim)
    install.perform_install(plan)

    written = (fake_home / ".zshrc").read_text()
    start, end = rcfile.find_block(written)
    assert printed == written[start:end] + "\n"
    assert ("PATH=" in printed) is path_shim


def test_install_main_rejects_an_unknown_shell(fake_home):
    assert install.install_main(["--shells=powershell", "--yes"]) == 1


def test_a_too_old_python_installs_nothing(fake_home, no_regen, monkeypatch, capsys):
    monkeypatch.setattr(install, "find_python", lambda: ("/usr/bin/python3", (3, 9, 6)))

    assert install.install_main(["--yes", "--shells=zsh"]) == 1
    assert "Python 3.12+ is required (found 3.9.6)" in capsys.readouterr().out
    assert not (fake_home / ".zshrc").exists()


def test_a_failed_tool_install_fails_the_install(fake_home, no_regen, monkeypatch):
    monkeypatch.setattr(install, "missing_binaries", lambda: ["ffprobe"])
    monkeypatch.setattr(install, "install_missing_binaries", lambda names, dry_run: False)

    assert install.install_main(["--yes", "--shells=zsh", "--install-deps"]) == 1
    assert (fake_home / ".zshrc").exists()


def test_no_completions_is_accepted_but_not_advertised(fake_home, capsys):
    assert install.install_main(["--print", "--shells=zsh", "--no-completions"]) == 0
    assert "--no-completions" not in install.build_install_parser().format_help()


# ---------------------------------------------------------------------------
# The wizard
# ---------------------------------------------------------------------------


@pytest.fixture
def scripted_wizard(fake_home, no_regen, monkeypatch):
    """The wizard with its prompts answered "yes" and recorded, and no tty."""
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(install, "missing_binaries", lambda: ["ffprobe"])
    monkeypatch.setattr(install, "install_missing_binaries", lambda names, dry_run: True)
    monkeypatch.setattr(install, "choose", lambda _title, _options, selected: list(selected))
    monkeypatch.setattr(install.shutil, "which", lambda binary: f"/usr/bin/{binary}")

    asked: list[str] = []

    def confirm(question, *, default):
        asked.append(question)
        return True

    monkeypatch.setattr(install, "confirm", confirm)
    return asked


def test_the_wizard_does_not_ask_what_the_plan_already_answered(fake_home, scripted_wizard):
    (fake_home / ".zshrc").write_text(LEGACY_RC)
    plan = install.InstallPlan(
        shells=["zsh"], python=sys.executable, sounds=False, path_shim=False, replace_legacy=True
    )

    assert install.wizard(plan, install_deps=True) == 0
    assert scripted_wizard == []
    record = machine.load_record()
    assert (record.sounds, record.path_shim) == (False, False)
    assert "SHELL_FUNCTIONS_BIN" not in (fake_home / ".zshrc").read_text()


def test_the_wizard_asks_when_the_plan_leaves_it_open(fake_home, scripted_wizard):
    (fake_home / ".zshrc").write_text(LEGACY_RC)

    assert install.wizard(install.InstallPlan(shells=["zsh"], python=sys.executable)) == 0
    assert len(scripted_wizard) == 4  # shim, sounds, legacy wrappers, missing tools


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


def test_uninstall_removes_everything_it_made(fake_home, no_regen, capsys):
    install.perform_install(install.InstallPlan(shells=["zsh"], python="python3"))
    history = machine.state_dir() / "history-args"
    history.parent.mkdir(parents=True)
    history.write_text("~/Movies\n")

    assert install.uninstall(purge=True) == 0
    assert shellgen.BEGIN_MARKER not in (fake_home / ".zshrc").read_text()
    assert not machine.shim_path().exists()
    assert not machine.config_dir().exists()
    assert not machine.state_dir().exists()


def test_uninstall_dry_run_says_what_it_would_remove(fake_home, no_regen, monkeypatch, capsys):
    monkeypatch.setenv("NO_COLOR", "1")
    install.perform_install(install.InstallPlan(shells=["zsh"], python="python3"))
    before = (fake_home / ".zshrc").read_text()
    capsys.readouterr()

    assert install.uninstall(dry_run=True, purge=True) == 0
    out = capsys.readouterr().out

    assert "would remove block from ~/.zshrc" in out
    assert "✓ removed" not in out
    assert "Uninstalled" not in out
    assert (fake_home / ".zshrc").read_text() == before
    assert machine.shim_path().exists()
    assert machine.config_file().exists()


def test_uninstall_without_purge_says_it_removes_the_record(
    fake_home, no_regen, monkeypatch, capsys
):
    """The record used to go silently, and on a dry run not at all."""
    monkeypatch.setenv("NO_COLOR", "1")
    install.perform_install(install.InstallPlan(shells=["zsh"], python="python3", path_shim=False))
    capsys.readouterr()

    assert install.uninstall(dry_run=True) == 0
    assert "would remove ~/.config/che/config.json" in capsys.readouterr().out
    assert machine.config_file().exists()

    assert install.uninstall() == 0
    assert "✓ removed ~/.config/che/config.json" in capsys.readouterr().out
    assert not machine.config_file().exists()
    assert machine.config_dir().exists()


def test_uninstall_rejects_another_builtins_flag(fake_home):
    with pytest.raises(SystemExit) as exit_info:
        install.uninstall_main(["--json"])
    assert exit_info.value.code == 1


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_refuses_outside_a_git_checkout(fake_home, fake_repo, tmp_path, capsys):
    """An npm install has no .git to pull, so update must say how to update instead."""
    package = tmp_path / "node_modules" / "@codebend3r" / "che"
    package.mkdir(parents=True)
    fake_repo(package)

    assert install.update() == 1
    captured = capsys.readouterr()
    assert f"npm install -g {PACKAGE_NAME}@latest" in captured.out + captured.err


def test_update_reports_a_branch_with_no_upstream(fake_home, fake_repo, git_repo, capsys):
    """rev-list fails without an upstream; that used to fall through to a pull
    and be reported as a diverged branch."""
    clone = git_repo("clone")
    git(clone, "checkout", "--quiet", "-b", "local-only")
    fake_repo(clone)

    assert install.update() == 1
    assert "no upstream" in capsys.readouterr().out


def test_update_check_stops_before_reinstalling(fake_home, fake_repo, git_repo, capsys):
    fake_repo(git_repo("clone"))

    assert install.update(check_only=True) == 0
    assert "Already up to date." in capsys.readouterr().out
    assert not machine.config_file().exists()


def test_update_refuses_to_install_under_a_too_old_python(
    fake_home, fake_repo, git_repo, monkeypatch, capsys
):
    """It used to write whatever find_python fell back to into every rc block."""
    fake_repo(git_repo("clone"))
    monkeypatch.setattr(install, "find_python", lambda: ("/usr/bin/python3", (3, 9, 6)))

    assert install.update() == 1
    assert "Python 3.12+ is required" in capsys.readouterr().out
    assert not machine.config_file().exists()
