"""The generated shell files have to be valid in the shells that source them.

A syntax error here does not fail loudly - it fails at the top of the user's
next shell, which is how a broken rc file eats an afternoon. So: parse every
generated file with the real shell where it is installed, and check the
wrappers say what the manifest says they should.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
import shellgen
from commands import COMMANDS, REPO, resolve

ZSH = shutil.which("zsh")
BASH = shutil.which("bash")


def parse_ok(shell: str, path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([shell, "-n", str(path)], capture_output=True, text=True, check=False)


@pytest.mark.skipif(not ZSH, reason="zsh is not installed")
def test_generated_zsh_parses(tmp_path):
    target = tmp_path / "che.zsh"
    target.write_text(shellgen.wrappers("zsh"))
    result = parse_ok(ZSH, target)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not BASH, reason="bash is not installed")
def test_generated_bash_parses(tmp_path):
    target = tmp_path / "che.bash"
    target.write_text(shellgen.wrappers("bash"))
    result = parse_ok(BASH, target)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not ZSH, reason="zsh is not installed")
def test_generated_zsh_completions_parse(tmp_path):
    target = tmp_path / "_che"
    target.write_text(shellgen.completions("zsh"))
    assert parse_ok(ZSH, target).returncode == 0


@pytest.mark.skipif(not BASH, reason="bash is not installed")
def test_generated_bash_completions_parse_on_bash_3(tmp_path):
    """macOS still ships bash 3.2, which has no `mapfile`."""
    target = tmp_path / "che.bash"
    target.write_text(shellgen.completions("bash"))
    assert parse_ok("/bin/bash", target).returncode == 0


@pytest.mark.parametrize("shell", shellgen.SHELLS)
def test_every_command_gets_a_wrapper(shell):
    text = shellgen.wrappers(shell)
    for command in COMMANDS:
        needle = f"function {command.name} " if shell == "fish" else f"{command.name}() {{"
        assert needle in text, f"{command.name} has no {shell} wrapper"
        if command.has_dry_twin:
            twin = (
                f"function {command.dry_name} " if shell == "fish" else f"{command.dry_name}() {{"
            )
            assert twin in text


@pytest.mark.parametrize("shell", shellgen.SHELLS)
def test_wrappers_never_hardcode_a_machine_path(shell):
    """These files are committed, so they must work from any clone location."""
    text = shellgen.wrappers(shell)
    assert "/Users/" not in text.replace("~/Developer/git/shell-functions", "")
    assert "/opt/homebrew" not in text


def test_dry_twin_flips_the_right_switch():
    text = shellgen.wrappers("zsh")
    assert 'DRY_RUN=true "$CHE_PYTHON" "$CHE_BIN/files/delete-by-ext.py"' in text
    assert 'DRY_RUN=false "$CHE_PYTHON" "$CHE_BIN/files/delete-by-ext.py"' in text
    # eject-all-drives spells its preview as a flag, not an environment variable.
    assert '"$CHE_BIN/drives/eject-all-drives.py" --dry-run' in text


def test_wrappers_preserve_the_scripts_exit_status():
    """The old wrappers returned playsound's status, not the script's."""
    text = shellgen.wrappers("zsh")
    assert "che_notify 6 $?" in text
    assert 'return "${2:-0}"' in text


def test_sound_is_optional():
    """playsound-N lives outside this repo; a machine without it must not print
    'command not found' after every command."""
    text = shellgen.wrappers("bash")
    assert 'command -v "playsound-$1" >/dev/null 2>&1' in text


def test_rc_block_is_small_and_marked(tmp_path):
    block = shellgen.rc_block("zsh", home=tmp_path, python="/usr/bin/python3")
    assert block.startswith(shellgen.BEGIN_MARKER)
    assert block.rstrip().endswith(shellgen.END_MARKER)
    assert str(tmp_path) in block
    assert "/usr/bin/python3" in block
    assert len(block.splitlines()) <= 8, "the rc block should stay tiny"


def test_rc_block_can_silence_sounds(tmp_path):
    block = shellgen.rc_block("zsh", home=tmp_path, python="python3", sounds=False)
    assert "CHE_SOUNDS=0" in block


def test_fish_block_uses_fish_syntax(tmp_path):
    block = shellgen.rc_block("fish", home=tmp_path, python="python3")
    assert "set -gx CHE_HOME" in block
    assert "export " not in block


def test_completions_offer_every_command():
    for shell in shellgen.SHELLS:
        text = shellgen.completions(shell)
        for command in COMMANDS:
            assert command.name in text


def test_completion_flags_come_from_the_manifest():
    text = shellgen.completions("bash")
    command = resolve("delete-by-ext").command
    for flag in command.flags:
        assert flag in text


def test_generation_is_deterministic():
    assert shellgen.generated_files() == shellgen.generated_files()


@pytest.mark.skipif(not ZSH, reason="zsh is not installed")
def test_a_colliding_alias_does_not_break_the_file(tmp_path):
    """zsh expands aliases while parsing, so `alias show-codecs=…` turns the
    wrapper's definition into a parse error that aborts everything after it.
    The guard has to stash the alias, define the functions, and put it back."""
    wrapper = tmp_path / "che.zsh"
    wrapper.write_text(shellgen.wrappers("zsh"))

    script = tmp_path / "probe.zsh"
    script.write_text(
        "alias show-codecs='echo mine'\n"
        f"source {wrapper}\n"
        "(( ${+functions[show-codecs]} )) && print function-defined\n"
        "(( ${+functions[update-brew]} )) && print later-wrapper-defined\n"
        "print alias=${aliases[show-codecs]}\n"
    )

    result = subprocess.run([ZSH, "-f", str(script)], capture_output=True, text=True, check=False)
    assert "function-defined" in result.stdout, result.stderr
    # A wrapper defined *after* the collision proves the file did not abort.
    assert "later-wrapper-defined" in result.stdout, result.stderr
    # The user aliased it on purpose, so it survives and still wins.
    assert "alias=echo mine" in result.stdout
    assert "parse error" not in result.stderr


@pytest.mark.skipif(not BASH, reason="bash is not installed")
def test_bash_guard_restores_a_colliding_alias(tmp_path):
    wrapper = tmp_path / "che.bash"
    wrapper.write_text(shellgen.wrappers("bash"))

    script = tmp_path / "probe.bash"
    script.write_text(
        "shopt -s expand_aliases\n"
        "alias show-codecs='echo mine'\n"
        f"source {wrapper}\n"
        "declare -F show-codecs >/dev/null && echo function-defined\n"
        "declare -F update-brew >/dev/null && echo later-wrapper-defined\n"
        "alias show-codecs\n"
    )

    result = subprocess.run([BASH, str(script)], capture_output=True, text=True, check=False)
    assert "function-defined" in result.stdout, result.stderr
    assert "later-wrapper-defined" in result.stdout, result.stderr
    assert "echo mine" in result.stdout


@pytest.mark.parametrize("shell", ["zsh", "bash"])
def test_the_guard_covers_every_name_the_file_defines(shell):
    text = shellgen.wrappers(shell)
    stash = text.split("_che_stash_aliases", 2)[2].split("\n\n")[0]
    for command in COMMANDS:
        assert command.name in stash, f"{command.name} is missing from the alias guard"


def test_readme_keeps_every_generated_marker():
    """A section that quietly loses its markers stops being checked, which is
    how a README goes stale without anyone noticing."""
    readme = (REPO / shellgen.README).read_text()
    for name in shellgen.readme_islands():
        assert f"<!-- che:{name} -->" in readme
        assert f"<!-- /che:{name} -->" in readme


def test_readme_islands_match_the_manifest():
    readme = (REPO / shellgen.README).read_text()
    assert shellgen.render_readme(readme) == readme, "run `bun run generate`"


def test_readme_documents_how_to_install():
    readme = (REPO / shellgen.README).read_text()
    assert "## Install" in readme
    assert "install.sh" in readme
    assert "--shells=" in readme
    assert "che uninstall" in readme
    assert "Python 3.12+" in readme


def test_render_readme_rejects_a_missing_marker():
    with pytest.raises(ValueError, match="markers"):
        shellgen.render_readme("# Shell Functions\n\nno markers here\n")
