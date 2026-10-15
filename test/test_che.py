"""End-to-end tests for the dispatcher, driven the way a user drives it.

These run ``bin/che.py`` as a subprocess: the point is the contract at the
shell prompt (exit codes, what lands on stdout, whether DRY_RUN reaches the
script), not the internals. The few pieces with real logic of their own - the
run path, the menu's dry-run reading - are also tested in-process.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import che as dispatcher
import pytest
import shellgen
from commands import BUILTIN_NAMES, resolve


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


@pytest.mark.parametrize("flags", [[], ["--json"]])
def test_list_rejects_an_unknown_category(che, flags):
    result = che(["list", "--category=nope", *flags])
    assert result.returncode == 1
    assert "Unknown category" in result.stdout


def test_list_filters_by_category_and_can_hide_the_twins(che):
    names = che(["list", "--category=files", "--no-dry"]).stdout.split()
    assert "delete-by-ext" in names
    assert "delete-by-ext-dr" not in names
    assert "show-codecs" not in names


def test_a_builtin_rejects_another_builtins_flag(che):
    """They used to share one parser, so `che doctor --purge` ran the doctor."""
    result = che(["doctor", "--purge"])
    assert result.returncode == 1
    assert "unrecognized arguments: --purge" in result.stdout


def test_every_builtin_has_a_main():
    assert set(dispatcher.BUILTIN_MAIN) == BUILTIN_NAMES


def test_suggest_offers_the_obvious_typo():
    assert "delete-by-ext" in dispatcher.suggest("delete-by-exts")
    assert "show-codecs" in dispatcher.suggest("codecs")


def test_unknown_command_suggests_the_closest(che):
    result = che(["delete-by-exts"])
    assert result.returncode == 1
    assert "Unknown command" in result.stdout
    assert "delete-by-ext" in result.stdout


def test_help_for_one_command_shows_its_usage(che):
    result = che(["help", "delete-by-ext"])
    assert result.returncode == 0
    assert "--ext" in result.stdout


def test_help_for_a_builtin_shows_its_own_usage(che):
    """It used to print the one-line summary under "(from `doctor --help`)"."""
    result = che(["help", "doctor"])
    assert result.returncode == 0
    assert "--json" in result.stdout


@pytest.mark.parametrize("form", [["{}"], ["--shell={}"], ["--shell", "{}"]])
def test_completions_are_printed_per_shell(che, form):
    for shell in shellgen.FLAVORS:
        result = che(["completions", *(part.format(shell) for part in form)])
        assert result.returncode == 0
        assert "delete-by-ext" in result.stdout


@pytest.mark.parametrize("args", [[], ["powershell"], ["zsh", "--purge"]])
def test_completions_rejects_a_missing_or_unknown_shell(che, args):
    assert che(["completions", *args]).returncode == 1


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


def test_a_missing_script_exits_127(capsys):
    command = dataclasses.replace(resolve("delete-by-ext").command, script="files/nope.py")
    assert dispatcher.run_command(dispatcher.Resolved(command), []) == 127
    assert dispatcher.exec_command(dispatcher.Resolved(command), []) == 127
    assert "Missing script" in capsys.readouterr().out


def test_the_run_path_matches_the_wrapper():
    variant = resolve("delete-by-ext-dr")
    argv, env = dispatcher._argv_env(variant, ["--ext=xyz"])
    assert argv[1:] == [str(variant.command.path), "--ext=xyz"]
    assert env == {"DRY_RUN": "true"}

    variant = resolve("list-permission")
    argv, env = dispatcher._argv_env(variant, ["Media"])
    assert argv[1:] == [str(variant.command.path), "Media"]
    assert env == {}


def test_a_builtin_runs_as_che_in_a_child():
    argv, env = dispatcher._argv_env(resolve("doctor"), ["--json"])
    assert argv[1:] == [str(Path(dispatcher.__file__).resolve()), "doctor", "--json"]
    assert env == {}


def test_a_child_killed_by_a_signal_reports_128_plus_n(monkeypatch):
    monkeypatch.setattr(dispatcher, "_argv_env", lambda *_: (["sh", "-c", "kill -TERM $$"], {}))
    assert dispatcher.run_command(resolve("btop"), []) == 128 + 15


# ---------------------------------------------------------------------------
# The menu's "changes files for real" question
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dry", "extra", "expected"),
    [
        (False, [], False),
        (True, [], True),
        (False, ["--dry-run"], True),
        (False, ["--dry-run=true"], True),
        # Every false spelling the script accepts must still ask.
        (False, ["--dry-run=0"], False),
        (False, ["--dry-run=no"], False),
        (False, ["--dry-run=False"], False),
        # On preview, but the typed flag wins over DRY_RUN=true.
        (True, ["--dry-run=false"], False),
        # The last one wins, as in the script's parser.
        (False, ["--dry-run", "--dry-run=off"], False),
        (True, ["--dry-run=0", "--dry-run"], True),
        # An unparseable value is an error in the script; ask anyway.
        (True, ["--dry-run=maybe"], False),
        # After `--` it is a positional, not the flag.
        (False, ["--", "--dry-run"], False),
        # Not the flag at all.
        (False, ["--dry-run-later"], False),
    ],
)
def test_effective_dry_reads_dry_run_like_the_script(dry, extra, expected):
    assert dispatcher.effective_dry(dry, extra) is expected


# ---------------------------------------------------------------------------
# Launching from the menu
# ---------------------------------------------------------------------------


@pytest.fixture
def answers(monkeypatch, no_color):
    """Script the menu's prompts, and record what would run instead of running it.

    ``answers(yes=[...], text=[...])`` feeds ``tui.confirm`` and ``tui.ask`` in
    order; either may hold an exception to raise. Returns the list each run's
    ``(name, extra)`` lands in.
    """
    ran: list[tuple[str, list[str]]] = []

    def _feed(values):
        queue = iter(values)

        def _answer(*_args, **_kwargs):
            value = next(queue)
            if isinstance(value, BaseException):
                raise value
            return value

        return _answer

    def _script(*, yes=(), text=()):
        monkeypatch.setattr(dispatcher.tui, "confirm", _feed(yes))
        monkeypatch.setattr(dispatcher.tui, "ask", _feed(text))
        return ran

    monkeypatch.setattr(
        dispatcher,
        "run_command",
        lambda target, extra: ran.append((target.name, extra)) or 0,
    )
    return _script


def test_the_echoed_command_line_is_the_one_to_copy(answers, capsys):
    ran = answers(text=["/my media", "xyz", ""])

    assert dispatcher.launch(resolve("delete-by-ext-dr"), prompt=True) == 0
    assert "$ che delete-by-ext-dr '--path=/my media' --ext=xyz\n" in capsys.readouterr().out
    assert ran == [("delete-by-ext-dr", ["--path=/my media", "--ext=xyz"])]


def test_a_builtin_gets_the_real_run_confirm(answers):
    """Enter on uninstall used to uninstall on the spot."""
    ran = answers(yes=[False])

    assert dispatcher.launch(resolve("uninstall"), prompt=False) == 130
    assert ran == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ([""], "Path to scan is required."),
        (["/media", "", "'unclosed"], "Extra arguments: No closing quotation"),
        ([KeyboardInterrupt()], ""),
    ],
)
def test_a_cancelled_prompt_runs_nothing(answers, capsys, text, message):
    ran = answers(text=text)

    assert dispatcher.launch(resolve("delete-by-ext-dr"), prompt=True) == 130
    out = capsys.readouterr().out
    assert out.rstrip().endswith("Cancelled.")
    assert message in out
    assert ran == []
