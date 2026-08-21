"""The command manifest is the source of truth, so it gets checked hardest.

Everything else - the wrappers, the completions, the menu, the doctor report -
is generated from ``bin/commands.py``. A mistake there shows up as a wrapper
that runs the wrong file or a flag nobody can pass, in every shell at once.
"""

from __future__ import annotations

import stat

import commands
import pytest
from commands import BUILTINS, CATEGORIES, COMMANDS, all_commands, command_names, resolve

BIN = commands.BIN


def test_every_script_exists_and_is_executable():
    for command in COMMANDS:
        if not command.script:
            continue
        script = BIN / command.script
        assert script.is_file(), f"{command.name} points at a missing script: {script}"
        assert script.stat().st_mode & stat.S_IXUSR, f"{script} is not executable"


def test_shell_only_commands_have_a_body():
    for command in COMMANDS:
        assert command.script or command.body, f"{command.name} has neither a script nor a body"


def test_names_are_unique_including_dry_twins():
    names = command_names()
    assert len(names) == len(set(names)), "two commands would define the same shell function"


def test_names_are_shell_function_safe():
    for name in command_names():
        assert name.replace("-", "").isalnum(), f"{name} is not a safe function name"
        assert not name.startswith("-")


def test_every_command_has_a_known_category():
    known = {category.key for category in CATEGORIES}
    for command in all_commands():
        assert command.category in known, f"{command.name} has category {command.category!r}"


def test_summaries_are_short_and_unpunctuated():
    for command in all_commands():
        assert command.summary, f"{command.name} has no summary"
        assert len(command.summary) <= 78, f"{command.name}'s summary is too long for the menu"
        assert not command.summary.endswith("."), f"{command.name}'s summary ends in a period"


def test_prompt_flags_are_flags_the_script_accepts():
    """A prompt that offers `--limit` to a script that spells it `--length`
    builds a command line the script rejects - which is exactly what happened
    to find-largest-files before this test existed."""
    for command in all_commands():
        for prompt in command.prompts:
            if not prompt.flag:
                continue
            assert prompt.flag in command.flags, f"{command.name}: {prompt.flag} is not in flags"


def test_dry_run_invocation_matches_style():
    for command in COMMANDS:
        if command.dry_run == "env":
            env, args = command.invocation(dry=True)
            assert env["DRY_RUN"] == "true"
            assert "--dry-run" not in args
            env, _ = command.invocation(dry=False)
            assert env["DRY_RUN"] == "false"
        elif command.dry_run == "flag":
            _, args = command.invocation(dry=True)
            assert args[-1] == "--dry-run"
            _, args = command.invocation(dry=False)
            assert "--dry-run" not in args


def test_destructive_commands_can_preview():
    """Anything that deletes or rewrites files needs a way to look first."""
    for command in COMMANDS:
        if not command.destructive:
            continue
        previewable = command.has_dry_twin or any(
            prompt.flag == "--dry-run" for prompt in command.prompts
        )
        assert previewable or command.no_preview_reason, (
            f"{command.name} is destructive with no preview and no stated reason"
        )


def test_resolve_handles_dry_suffix_and_unknown_names():
    assert resolve("delete-by-ext").command.name == "delete-by-ext"
    assert resolve("delete-by-ext").dry is False

    dry = resolve("delete-by-ext-dr")
    assert dry is not None
    assert dry.command.name == "delete-by-ext"
    assert dry.dry is True

    assert resolve("nope") is None
    # A -dr suffix on a command that has no preview twin is not a command.
    assert resolve("find-largest-files-dr") is None


def test_builtins_do_not_collide_with_scripts():
    script_names = {command.name for command in COMMANDS}
    for builtin in BUILTINS:
        assert builtin.name not in script_names


def test_required_binaries_are_reachable_from_commands():
    index = commands.required_binaries()
    for binary, users in index.items():
        assert users, f"{binary} is required by nothing"
        for name in users:
            assert resolve(name) is not None


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("delete-by-ext", "delete-by-ext"),
        ("dbe", "delete-by-ext"),
        ("extensions", "delete-by-ext"),
    ],
)
def test_fuzzy_match_finds_a_command(query, expected):
    target = resolve(expected).command
    assert commands.fuzzy_match(query, target) is not None


def test_fuzzy_match_rejects_nonsense():
    target = resolve("delete-by-ext").command
    assert commands.fuzzy_match("zzzz", target) is None


def test_suggest_offers_the_obvious_typo():
    assert "delete-by-ext" in commands.suggest("delete-by-exts")
    assert "show-codecs" in commands.suggest("codecs")


def test_paths_do_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    """The wrappers run from wherever the user happens to be, so every path in
    the manifest is resolved from the module's own location."""
    monkeypatch.chdir(tmp_path)
    assert commands.BIN.is_absolute()
    assert commands.REPO.is_absolute()
    assert (commands.BIN / "utils.py").exists()
    assert resolve("delete-by-ext").command.path.exists()
