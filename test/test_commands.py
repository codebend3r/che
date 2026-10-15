"""The command manifest is the source of truth, so it gets checked hardest.

Everything else - the wrappers, the completions, the menu, the doctor report -
is generated from ``bin/commands.py``. A mistake there shows up as a wrapper
that runs the wrong file or a flag nobody can pass, in every shell at once.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys

import commands
import pytest
from commands import (
    BUILTIN_NAMES,
    BUILTINS,
    CATEGORIES,
    COMMANDS,
    Command,
    Resolved,
    all_commands,
    command_names,
    grouped,
    resolve,
    variants,
)

BIN = commands.BIN


def test_every_script_exists_and_is_executable():
    for command in COMMANDS:
        assert command.script, f"{command.name} has no script"
        script = BIN / command.script
        assert script.is_file(), f"{command.name} points at a missing script: {script}"
        assert script.stat().st_mode & stat.S_IXUSR, f"{script} is not executable"


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
    to find-largest-files before this test existed. A yes/no prompt passes the
    bare flag, so it must be a switch; any other passes `--flag=answer`, so the
    flag must take a value."""
    for command in all_commands():
        for prompt in command.prompts:
            if not prompt.flag:
                continue
            spelled = prompt.flag if prompt.kind == "bool" else f"{prompt.flag}="
            assert spelled in command.flags, f"{command.name}: {spelled} is not in flags"


def test_list_fields_are_tuples():
    """`flags=("--path")` is a string, and iterating it offered `- - p a t h`
    as completions in every shell."""
    with pytest.raises(TypeError, match="flags must be a tuple"):
        Command(name="x", category="files", summary="x", flags=("--path"))


def test_flags_are_long_options():
    for command in all_commands():
        for flag in command.flags:
            assert re.fullmatch(r"--[a-z0-9-]+=?", flag), f"{command.name}: odd flag {flag!r}"
        assert len(set(command.flag_names)) == len(command.flags), f"{command.name}: duplicate"


# `  --path DIR  help`: an option line in argparse's help. A metavar in brackets
# (`--watch [SECONDS]`) is optional, so that flag is completed bare.
_HELP_OPTION = re.compile(r"^  (--[a-z0-9-]+)( [A-Z])?")


def _documented_flags(help_text: str) -> set[str]:
    """The long options an argparse ``--help`` documents, spelled the manifest's way.

    A hidden option (``help=argparse.SUPPRESS``, which every ``--flag=false``
    companion is) is not documented, so it is not counted.
    """
    _, _, options = help_text.partition("\noptions:\n")
    flags = set()
    for line in options.splitlines():
        if line and not line.startswith(" "):
            break  # the next section, such as an epilog's "Examples:"
        if match := _HELP_OPTION.match(line):
            flags.add(match.group(1) + ("=" if match.group(2) else ""))
    return flags


def _help_flags(script: str) -> set[str]:
    result = subprocess.run(
        [sys.executable, str(BIN / script), "--help"],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "NO_COLOR": "1"},
    )
    return _documented_flags(result.stdout)


@pytest.mark.parametrize(
    "command",
    # btop hands every argument to btop and has no options of its own.
    [command for command in COMMANDS if command.name != "btop"],
    ids=lambda command: command.name,
)
def test_flags_match_the_scripts_own_help(command):
    """The manifest's flags feed every shell's completions and the menu, and
    nothing else ties them to the parser - update-brew's three newest flags
    went missing for exactly that reason. A fixed argument (`--watch`,
    `--dry-run=false`) is a flag the script takes too."""
    fixed = {arg.partition("=")[0] for arg in command.args}
    assert _help_flags(command.script) == {*command.flags, *fixed}


@pytest.mark.parametrize("command", BUILTINS, ids=lambda command: command.name)
def test_builtin_flags_match_their_parser(command, capsys):
    """The same check for the built-ins, which once shared a single parser and
    advertised flags (`update --yes`, `list --dry`) that none of them took."""
    import che

    with pytest.raises(SystemExit) as exit_info:
        che.BUILTIN_MAIN[command.name](["--help"])
    assert exit_info.value.code == 0

    assert _documented_flags(capsys.readouterr().out) == set(command.flags)


def test_dry_run_invocation_matches_style():
    for command in COMMANDS:
        plain, dry = Resolved(command), Resolved(command, dry=True)
        if command.dry_run == "env":
            assert dry.env["DRY_RUN"] == "true"
            assert "--dry-run" not in dry.args
            assert plain.env["DRY_RUN"] == "false"
        elif command.dry_run == "flag":
            assert dry.args[-1] == "--dry-run"
            assert "--dry-run" not in plain.args
        else:
            assert (plain.env, plain.args) == (dry.env, dry.args) == ({}, command.args)


def test_destructive_commands_can_preview():
    """Anything that deletes or rewrites files needs a way to look first."""
    for command in all_commands():
        if not command.destructive:
            continue
        assert command.preview or command.no_preview_reason, (
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


def test_variants_put_each_twin_right_after_its_command():
    names = [variant.name for variant in variants(COMMANDS)]
    assert names[names.index("delete-by-ext") + 1] == "delete-by-ext-dr"


def test_a_twin_has_its_own_name_sound_and_summary():
    command = resolve("delete-duplicate-videos").command
    plain, dry = command.variants()
    assert (plain.name, plain.sound) == ("delete-duplicate-videos", command.sound)
    assert (dry.name, dry.sound) == ("delete-duplicate-videos-dr", command.dry_sound)
    assert plain.summary("preview") == command.summary
    assert dry.summary("preview") == f"{command.summary} (preview)"
    assert resolve("delete-duplicate-videos-dr") == Resolved(command, dry=True)


def test_grouped_keeps_category_order_and_skips_empty_ones():
    groups = grouped(COMMANDS)
    keys = [category.key for category, _ in groups]
    assert keys == ["git", "video", "files", "drives", "system"]
    assert sum(len(members) for _, members in groups) == len(COMMANDS)
    for category, members in groups:
        assert all(member.category == category.key for member in members)


def test_builtin_means_handled_by_che_itself():
    assert {command.name for command in all_commands() if command.builtin} == BUILTIN_NAMES
    for command in BUILTINS:
        assert not command.script


def test_paths_do_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    """The wrappers run from wherever the user happens to be, so every path in
    the manifest is resolved from the module's own location."""
    monkeypatch.chdir(tmp_path)
    assert commands.BIN.is_absolute()
    assert commands.REPO.is_absolute()
    assert (commands.BIN / "utils.py").exists()
    assert resolve("delete-by-ext").command.path.exists()


def test_version_is_the_package_json_version():
    """One bump in package.json moves the npm release and `che --version` together."""
    package = json.loads((commands.REPO / "package.json").read_text(encoding="utf-8"))
    assert commands.VERSION == package["version"]
    assert commands.PACKAGE_NAME == package["name"]
