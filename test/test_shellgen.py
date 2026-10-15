"""The generated shell files have to be valid in the shells that source them.

A syntax error here does not fail loudly - it fails at the top of the user's
next shell, which is how a broken rc file eats an afternoon. So: parse every
generated file with the real shell where it is installed, and check the
wrappers say what the manifest says they should.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import shellgen
from commands import COMMANDS, REPO

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


@pytest.mark.parametrize("shell", shellgen.FLAVORS)
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


@pytest.mark.parametrize("shell", shellgen.FLAVORS)
def test_wrappers_never_hardcode_a_machine_path(shell):
    """These files are committed, so they must work from any clone location."""
    text = shellgen.wrappers(shell)
    assert "/Users/" not in text
    assert "/opt/homebrew" not in text


@pytest.fixture
def run_wrappers(tmp_path):
    """Source the bash wrappers against a stub interpreter and run ``lines``.

    The stub prints the ``DRY_RUN`` it was given and its argv, then exits 3.
    PATH holds only the system directories plus ``tmp_path/bin``, so no real
    ``playsound-N`` is reachable unless a test puts one there.
    """
    stub = tmp_path / "python"
    stub.write_text('#!/bin/sh\necho "DRY_RUN=${DRY_RUN:-} $*"\nexit 3\n')
    stub.chmod(0o755)
    (tmp_path / "bin").mkdir()
    wrapper = tmp_path / "che.bash"
    wrapper.write_text(shellgen.wrappers("bash"))

    def _run(*lines: str, **env: str) -> subprocess.CompletedProcess[str]:
        probe = tmp_path / "probe.bash"
        probe.write_text(f"source {wrapper}\n" + "".join(f"{line}\n" for line in lines))
        environment = {
            "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
            "CHE_HOME": str(tmp_path / "che"),
            "CHE_PYTHON": str(stub),
            **env,
        }
        return subprocess.run(
            [BASH, str(probe)], capture_output=True, text=True, env=environment, check=False
        )

    return _run


@pytest.mark.skipif(not BASH, reason="bash is not installed")
def test_wrappers_pass_the_right_switch_and_keep_the_scripts_status(tmp_path, run_wrappers):
    """Each wrapper runs its script with the preview switch its style calls for,
    forwards its arguments, and returns the script's own exit status - the old
    wrappers returned playsound's. With no playsound installed, nothing is
    printed about it."""
    result = run_wrappers(
        'delete-by-ext-dr --x; echo "status=$?"',
        'delete-by-ext --x; echo "status=$?"',
        'eject-all-drives-dr; echo "status=$?"',
        'update-from-origin; echo "status=$?"',
    )

    bin_dir = tmp_path / "che" / "bin"
    assert result.stdout.splitlines() == [
        f"DRY_RUN=true {bin_dir}/files/delete-by-ext.py --x",
        "status=3",
        f"DRY_RUN=false {bin_dir}/files/delete-by-ext.py --x",
        "status=3",
        f"DRY_RUN= {bin_dir}/drives/eject-all-drives.py --dry-run",
        "status=3",
        f"DRY_RUN= {bin_dir}/git/sync-all-branches.py --dry-run=false",
        "status=3",
    ]
    assert result.stderr == ""


@pytest.mark.skipif(not BASH, reason="bash is not installed")
@pytest.mark.parametrize(
    ("sounds", "plays"), [("", True), ("1", True), ("yes", True), ("0", False)]
)
def test_only_che_sounds_0_silences_the_chime(tmp_path, run_wrappers, sounds, plays):
    """The same rule as the fish wrappers: anything but `0` plays."""
    played = tmp_path / "played"
    chime = tmp_path / "bin" / "playsound-6"
    chime.write_text(f'#!/bin/sh\ntouch "{played}"\n')
    chime.chmod(0o755)

    result = run_wrappers("delete-by-ext --x", CHE_SOUNDS=sounds)

    assert result.stderr == ""
    assert played.exists() is plays


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


@pytest.mark.parametrize(
    ("shell", "line"),
    [
        ("zsh", 'case ":$PATH:" in *:/x/bin:*) ;; *) PATH=/x/bin:"$PATH" ;; esac'),
        ("bash", 'case ":$PATH:" in *:/x/bin:*) ;; *) PATH=/x/bin:"$PATH" ;; esac'),
        ("fish", "if not contains /x/bin $PATH\n    set -gx PATH /x/bin $PATH\nend"),
    ],
)
def test_rc_block_puts_the_shim_directory_on_path_last(tmp_path, shell, line):
    """`che install` writes this block, and `--print` shows the same, when the shim is on."""
    block = shellgen.rc_block(shell, home=tmp_path, python="python3", path_dir=Path("/x/bin"))
    assert block.endswith(f"\n{line}\n{shellgen.END_MARKER}\n")
    bare = shellgen.rc_block(shell, home=tmp_path, python="python3")
    assert "PATH" not in bare


@pytest.mark.skipif(not ZSH, reason="zsh is not installed")
def test_rc_block_quotes_awkward_paths(tmp_path):
    """Every value in the block survives a quote, a `$`, a backtick and a
    space - and the PATH line, run twice, adds its directory once."""
    home = tmp_path / "it's a home"
    shim = tmp_path / "a $dir `x` it's"
    block = shellgen.rc_block("zsh", home=home, python='/odd "py"/python3', path_dir=shim)
    probe = tmp_path / "probe.zsh"
    probe.write_text(block + block + 'print -r -- "$CHE_HOME|$CHE_PYTHON"\nprint -r -- "$PATH"\n')
    result = subprocess.run([ZSH, "-f", str(probe)], capture_output=True, text=True, check=False)
    assert result.stderr == ""
    names, path = result.stdout.splitlines()
    assert names == f'{home}|/odd "py"/python3'
    assert path.split(":").count(str(shim)) == 1
    assert path.startswith(f"{shim}:")


def test_fish_completes_values_and_paths():
    text = shellgen.completions("fish")
    assert "complete -c show-codecs -l path -r -F\n" in text
    assert "complete -c show-codecs -l verbose\n" in text
    assert "complete -c all-actions -l repo-limit -r\n" in text


def test_completions_offer_every_command():
    for shell in shellgen.FLAVORS:
        text = shellgen.completions(shell)
        for command in COMMANDS:
            assert command.name in text


# Every name the wrapper file defines, `che` and its sound helper included: an
# alias on any of them used to abort the file before a single wrapper loaded.
GUARDED = shellgen.defined_names()


@pytest.mark.skipif(not ZSH, reason="zsh is not installed")
def test_colliding_aliases_do_not_break_the_zsh_file(tmp_path):
    """zsh expands aliases while parsing, so `alias show-codecs=…` turns the
    wrapper's definition into a parse error that aborts everything after it.
    The guard has to stash every such alias, define the functions, and put the
    aliases back - so alias every wrapper's name, and check them all."""
    wrapper = tmp_path / "che.zsh"
    wrapper.write_text(shellgen.wrappers("zsh"))

    script = tmp_path / "probe.zsh"
    script.write_text(
        "".join(f"alias -- {name}='echo mine'\n" for name in GUARDED)
        + f"source {wrapper}\n"
        + "".join(
            f"(( ${{+functions[{name}]}} )) || print missing={name}\n"
            f"[[ ${{aliases[{name}]-}} == 'echo mine' ]] || print lost-alias={name}\n"
            for name in GUARDED
        )
    )

    result = subprocess.run([ZSH, "-f", str(script)], capture_output=True, text=True, check=False)
    assert result.stdout == "", result.stdout + result.stderr
    assert "parse error" not in result.stderr


@pytest.mark.skipif(not BASH, reason="bash is not installed")
def test_colliding_aliases_do_not_break_the_bash_file(tmp_path):
    wrapper = tmp_path / "che.bash"
    wrapper.write_text(shellgen.wrappers("bash"))

    script = tmp_path / "probe.bash"
    script.write_text(
        "shopt -s expand_aliases\n"
        + "".join(f"alias {name}='echo mine'\n" for name in GUARDED)
        + f"source {wrapper}\n"
        + "".join(
            f"declare -F {name} >/dev/null || echo missing={name}\n"
            f'[ "$(alias {name} 2>/dev/null)" = "alias {name}=\'echo mine\'" ]'
            f" || echo lost-alias={name}\n"
            for name in GUARDED
        )
    )

    result = subprocess.run([BASH, str(script)], capture_output=True, text=True, check=False)
    assert result.stdout == "", result.stdout + result.stderr


def test_generated_files_in_the_repo_are_current():
    """The wrappers, completions, `.zshrc` shim and README islands all match
    the manifest - and every README marker is still there, or this raises."""
    assert shellgen.sync_generated(dry_run=True) == [], "run `bun run generate` and commit"


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
