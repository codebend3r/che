"""Tests for bin/video/detect-green-magenta-videos.py.

Its flags are checked after OpenCV loads, so these run only where the venv the
script re-execs into exists.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

SCRIPT = "video/detect-green-magenta-videos.py"

# The script's own VENV_PYTHON. Not read through load_script: importing the
# script without cv2 re-execs the importing process, which here is pytest.
VENV_PYTHON = os.environ.get(
    "DETECT_GM_PYTHON", str(Path.home() / ".venvs" / "green-magenta" / "bin" / "python")
)


@pytest.mark.skipif(
    not os.access(VENV_PYTHON, os.X_OK), reason="needs the green-magenta OpenCV venv"
)
@pytest.mark.parametrize("samples", ["0", "-1", "x"])
def test_rejects_a_sample_count_that_is_not_positive(tmp_path, run_script, samples):
    """Regression: 0 skipped every video and a negative count crashed numpy."""
    result = run_script(SCRIPT, [str(tmp_path), f"--samples={samples}"])

    assert result.returncode == 1
    assert f"❌ --samples must be a positive integer (got: {samples})" in result.stdout
