"""Shared fixtures for the script test suites.

The scripts under ``bin/`` are standalone executables, not an importable
package, so the tests drive them the way a user does: as a subprocess, checking
exit codes and the filesystem afterwards. That is the same contract the old
bash suites tested, so a passing suite means the same things it used to.

A few unit tests import the libraries at the ``bin/`` root directly - those ARE
importable, and testing ``format_bytes``/``parse_size`` through a subprocess
would prove less and run slower.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN = REPO_ROOT / "bin"

# Make bin/utils.py importable, mirroring what every script does at startup.
sys.path.insert(0, str(BIN))

EMAIL = "test@example.com"


def load_script(relative: str) -> ModuleType:
    """Import a script under ``bin/`` by path, for suites that unit-test its pure parts.

    Script filenames have dashes in them, so they cannot be imported by name.
    The module is registered in ``sys.modules`` before it runs, as an import
    would, so a ``@dataclass`` in the script can resolve its own module.
    """
    path = BIN / relative
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd`` and return its stripped stdout, raising on failure."""
    completed = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def local_branches(cwd: Path) -> list[str]:
    """The short names of ``cwd``'s local branches."""
    return git(cwd, "for-each-ref", "--format=%(refname:lstrip=2)", "refs/heads").split()


def commit(cwd: Path, name: str, *, when: str = "") -> None:
    """Commit one new file named ``name``, optionally with a fixed committer date."""
    path = cwd / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{name}\n")
    git(cwd, "add", name)
    env = {**os.environ, "GIT_COMMITTER_DATE": when} if when else None
    subprocess.run(
        ["git", "commit", "--quiet", "-m", name], cwd=cwd, env=env, check=True, capture_output=True
    )


@pytest.fixture
def git_repo(
    tmp_path: Path, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str], Path]:
    """Factory for clones of one bare ``origin``, each with a test identity.

    ``git_repo("work")`` clones ``tmp_path/origin.git`` into ``tmp_path/work``.
    The first call also creates the origin and pushes a first commit on
    ``main`` (a ``README.md``), so the clone tracks ``origin/main``. A later
    call clones the same origin, as a second machine would.

    HOME is empty (``fake_home``) and the system config is off for the whole
    test, so the developer's own git config (commit.gpgsign, core.hooksPath,
    init.templateDir, pull.rebase) reaches neither the fixture's git nor the
    code under test, in-process or as a subprocess.
    """
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)

    origin = tmp_path / "origin.git"

    def _clone(name: str = "work") -> Path:
        seed = not origin.exists()
        if seed:
            origin.mkdir()
            git(origin, "init", "--bare", "--initial-branch=main", "--quiet")

        path = tmp_path / name
        git(tmp_path, "clone", "--quiet", str(origin), str(path))
        git(path, "config", "user.email", EMAIL)
        git(path, "config", "user.name", "Test")

        if seed:
            (path / "README.md").write_text("hello\n")
            git(path, "add", "README.md")
            git(path, "commit", "--quiet", "-m", "init")
            git(path, "push", "--quiet", "--set-upstream", "origin", "main")
        return path

    return _clone


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty HOME, with every variable that could lead elsewhere unset.

    The installer resolves every path from the environment at call time, so
    this is all it takes to keep a test away from the developer's own dotfiles.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    for name in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "ZDOTDIR"):
        monkeypatch.delenv(name, raising=False)
    return home


@pytest.fixture
def no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plain output from the in-process log helpers, whatever the terminal."""
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture
def fake_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str, str], Path]:
    """Factory for stub executables first on PATH.

    ``fake_bin("brew", 'echo "$*" >> calls')`` writes ``#!/bin/sh`` plus that
    body as an executable ``brew`` and returns its path. PATH is set in the
    environment, so in-process code and ``run_script`` subprocesses both see it.
    """
    directory = tmp_path / "fake-bin"

    def _make(name: str, body: str) -> Path:
        if not directory.exists():
            directory.mkdir()
            monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")
        stub = directory / name
        stub.write_text(f"#!/bin/sh\n{body}")
        stub.chmod(0o755)
        return stub

    return _make


@pytest.fixture
def no_regen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep an install from rewriting the repo's own generated ``shell/`` files."""
    import shellgen

    monkeypatch.setattr(shellgen, "sync_generated", lambda dry_run=False: [])


@pytest.fixture
def run_script() -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run one of the scripts under ``bin/`` and return the completed process.

    ``env`` entries are ADDED to the current environment, so a test can set
    ``DRY_RUN`` without wiping PATH out from under the interpreter.
    """

    def _run(
        relative: str,
        args: Sequence[str] = (),
        *,
        env: dict[str, str] | None = None,
        check: bool = False,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        script = BIN / relative
        assert script.is_file(), f"no such script: {script}"

        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            check=check,
            cwd=cwd,
            env={**os.environ, "NO_COLOR": "1", **(env or {})},
        )

    return _run
