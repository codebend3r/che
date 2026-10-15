"""Tests for bin/system/btop-launch.py.

HOME points at a temporary directory holding the btop.conf under test, and
fake ``defaults`` and ``btop`` binaries first on PATH stand in for macOS and
for btop itself, so the suite needs neither and runs on Linux CI as well.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SCRIPT = "system/btop-launch.py"


@pytest.fixture
def launch(tmp_path, run_script, fake_bin):
    """Run the script in Dark or Light mode. Returns (result, btop's argv)."""
    home = tmp_path / "home"
    (home / ".config" / "btop").mkdir(parents=True)
    btop_argv = tmp_path / "btop.argv"

    # `defaults read -g AppleInterfaceStyle` prints "Dark" in Dark mode and
    # exits non-zero, the key being absent, in Light mode.
    fake_bin("defaults", '[ "$FAKE_DARK" = 1 ] && echo Dark && exit 0\nexit 1\n')
    fake_bin("btop", f': > "{btop_argv}"\nfor arg in "$@"; do echo "$arg" >> "{btop_argv}"; done\n')

    def _launch(*args: str, dark: bool = True):
        result = run_script(
            SCRIPT,
            args,
            env={"HOME": str(home), "FAKE_DARK": "1" if dark else "0"},
            check=True,
        )
        launched = btop_argv.read_text().splitlines() if btop_argv.exists() else None
        return result, launched

    return _launch


@pytest.fixture
def conf(tmp_path) -> Path:
    return tmp_path / "home" / ".config" / "btop" / "btop.conf"


def test_dark_mode_theme_is_written_and_crlf_survives(launch, conf):
    conf.write_bytes(b'update_ms = 2000\r\ncolor_theme = "Default"\r\nshown_boxes = "cpu"\r\n')

    result, launched = launch(dark=True)

    assert conf.read_bytes() == (
        b'update_ms = 2000\r\ncolor_theme = "gruvbox_dark_v2"\r\nshown_boxes = "cpu"\r\n'
    )
    assert "btop theme -> gruvbox_dark_v2" in result.stdout
    assert launched == []


def test_light_mode_theme(launch, conf):
    conf.write_text('color_theme = "gruvbox_dark_v2"\nupdate_ms = 2000\n')

    launch(dark=False)

    assert conf.read_text() == 'color_theme = "gruvbox_light"\nupdate_ms = 2000\n'


def test_cr_only_config_keeps_its_other_lines(launch, conf):
    """No `\\n` makes the whole file one line; the match must stop at the `\\r`."""
    conf.write_bytes(b'color_theme = "Default"\rupdate_ms = 2000\r')

    launch(dark=False)

    assert conf.read_bytes() == b'color_theme = "gruvbox_light"\rupdate_ms = 2000\r'


def test_arguments_pass_through_to_btop(launch, conf):
    conf.write_text('color_theme = "Default"\n')

    _, launched = launch("--utf-force", "--preset", "1")

    assert launched == ["--utf-force", "--preset", "1"]


def test_missing_config_still_launches(launch, conf):
    result, launched = launch()

    assert not conf.exists()
    assert "btop config not found" in result.stdout
    assert launched == []


def test_help_does_not_launch(launch, conf):
    result, launched = launch("--help")

    assert "Usage:" in result.stdout
    assert launched is None
