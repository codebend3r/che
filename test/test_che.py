"""End-to-end tests for the dispatcher, driven the way a user drives it.

These run ``bin/che.py`` as a subprocess: the point is the contract at the
shell prompt (exit codes, what lands on stdout, whether DRY_RUN reaches the
script), not the internals.
"""

from __future__ import annotations

import json

import pytest
import shellgen


@pytest.fixture
def che(run_script, tmp_path):
    def _run(args, **kwargs):
        env = {"HOME": str(tmp_path / "home"), **kwargs.pop("env", {})}
        (tmp_path / "home").mkdir(exist_ok=True)
        return run_script("che.py", args, env=env, **kwargs)

    return _run


def test_version(che):
    result = che(["--version"])
    assert result.returncode == 0
    assert result.stdout.startswith("che ")


def test_help_lists_commands_by_category(che):
    result = che(["--help"])
    assert result.returncode == 0
    assert "delete-by-ext" in result.stdout
    assert "VIDEO" in result.stdout
    assert "(+delete-by-ext-dr)" in result.stdout


def test_no_arguments_without_a_terminal_prints_help(che):
    """Piped or scripted, `che` must not try to open a full-screen menu."""
    result = che([])
    assert result.returncode == 0
    assert "USAGE" in result.stdout


def test_list_includes_dry_twins(che):
    result = che(["list"])
    names = result.stdout.split()
    assert "delete-by-ext" in names
    assert "delete-by-ext-dr" in names
    assert "doctor" in names


def test_list_json_is_machine_readable(che):
    result = che(["list", "--json"])
    payload = json.loads(result.stdout)
    entry = next(item for item in payload if item["name"] == "delete-by-ext")
    assert entry["script"] == "files/delete-by-ext.py"
    assert entry["destructive"] is True
    assert "--ext" in entry["flags"]


def test_list_rejects_an_unknown_category(che):
    result = che(["list", "--category=nope"])
    assert result.returncode == 1
    assert "Unknown category" in result.stdout


def test_unknown_command_suggests_the_closest(che):
    result = che(["delete-by-exts"])
    assert result.returncode == 1
    assert "Unknown command" in result.stdout
    assert "delete-by-ext" in result.stdout


def test_help_for_one_command_shows_its_usage(che):
    result = che(["help", "delete-by-ext"])
    assert result.returncode == 0
    assert "--ext" in result.stdout


def test_completions_are_printed_per_shell(che):
    for shell in shellgen.SHELLS:
        result = che(["completions", shell])
        assert result.returncode == 0
        assert "delete-by-ext" in result.stdout
    assert che(["completions", "powershell"]).returncode == 1


def test_install_print_emits_the_block(che):
    result = che(["install", "--print"])
    assert result.returncode == 0
    assert shellgen.BEGIN_MARKER in result.stdout
    assert shellgen.END_MARKER in result.stdout


def test_doctor_json_lists_checks(che):
    result = che(["doctor", "--json"])
    payload = json.loads(result.stdout)
    names = {check["name"] for check in payload["checks"]}
    assert "python" in names
    assert "generated files" in names


def test_running_a_command_passes_arguments_through(che, tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * 2048)
    result = che(["find-largest-files", f"--path={tmp_path}", "--length=1"])
    assert result.returncode == 0
    assert "big.bin" in result.stdout


def test_dry_twin_previews_and_the_plain_name_acts(che, tmp_path):
    """The wrapper's whole job is setting DRY_RUN correctly. Check it end to end."""
    target = tmp_path / "junk.xyz"
    keeper = tmp_path / "keep.mkv"
    target.write_text("delete me")
    keeper.write_text("keep me")

    preview = che(["delete-by-ext-dr", f"--path={tmp_path}", "--ext=xyz"])
    assert preview.returncode == 0
    assert target.exists(), "the -dr twin deleted a file"

    real = che(["delete-by-ext", f"--path={tmp_path}", "--ext=xyz"])
    assert real.returncode == 0
    assert not target.exists(), "the plain wrapper did not delete"
    assert keeper.exists()


def test_a_failing_command_returns_its_own_exit_code(che):
    result = che(["delete-by-ext", "--nonsense"])
    assert result.returncode == 1
