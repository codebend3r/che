"""Shared fixtures for the script test suites.

The scripts under ``bin/`` are standalone executables, not an importable
package, so the tests drive them the way a user does: as a subprocess, checking
exit codes and the filesystem afterwards. That is the same contract the old
bash suites tested, so a passing suite means the same things it used to.

A few unit tests import ``bin/utils.py`` directly - that one IS importable, and
testing ``format_bytes``/``parse_size`` through a subprocess would prove less
and run slower.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN = REPO_ROOT / "bin"

# Make bin/utils.py importable, mirroring what every script does at startup.
sys.path.insert(0, str(BIN))


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
    ) -> subprocess.CompletedProcess[str]:
        import os

        script = BIN / relative
        assert script.is_file(), f"no such script: {script}"

        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            check=check,
            env={**os.environ, "NO_COLOR": "1", **(env or {})},
        )

    return _run
