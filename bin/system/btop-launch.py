#!/usr/bin/env python3
"""🖥️  Launch btop with a gruvbox theme that follows the macOS appearance.

Light mode uses ``gruvbox_light``, Dark mode ``gruvbox_dark_v2``. The chosen
theme is written into ``btop.conf`` before launch, because btop reads its
config once at start.

Usage:
  btop-launch.py [btop-args...]

Any extra arguments are passed straight through to btop.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import info, require_binary, run, warning

__version__ = "1.0.1"

CONF = Path.home() / ".config" / "btop" / "btop.conf"
LIGHT_THEME = "gruvbox_light"
DARK_THEME = "gruvbox_dark_v2"

USAGE = f"""Usage:
  btop-launch.py [btop-args...]

Description:
  🖥️  Set btop's color_theme to match the current macOS appearance
  ({LIGHT_THEME} in Light mode, {DARK_THEME} in Dark mode), then exec btop.
  Any extra arguments are passed straight through to btop.
"""

# `[^\S\n]` rather than `\s`: \s matches newlines, so a config with a line
# break between "color_theme" and "=" would have two lines collapsed into one.
# perl -p works a line at a time and cannot do that.
_COLOR_THEME_RE = re.compile(r"^color_theme[^\S\n]*=.*$", re.MULTILINE)


def current_theme() -> str:
    """Pick the theme matching the macOS appearance.

    ``defaults read -g AppleInterfaceStyle`` prints "Dark" in Dark mode and
    exits non-zero (the key is absent) in Light mode.
    """
    completed = run(["defaults", "read", "-g", "AppleInterfaceStyle"], check=False, capture=True)
    value = (completed.stdout or "").strip() if completed.returncode == 0 else ""
    return DARK_THEME if value == "Dark" else LIGHT_THEME


def apply_theme(theme: str) -> None:
    """Rewrite the ``color_theme`` line in btop.conf, leaving the rest alone."""
    if not CONF.is_file():
        warning(f"btop config not found at {CONF}; launching with existing theme")
        return

    try:
        # newline="" so existing CRLF (or CR) line endings survive the
        # round-trip; read_text/write_text would rewrite every line ending in
        # the file, where `perl -i` only ever touched the matched line.
        # surrogateescape so a config carrying non-UTF-8 bytes still round-trips
        # instead of raising and leaving btop unlaunchable.
        with CONF.open("r", encoding="utf-8", errors="surrogateescape", newline="") as handle:
            original = handle.read()
    except OSError as exc:
        warning(f"Could not read {CONF}: {exc}; launching with existing theme")
        return

    updated, count = _COLOR_THEME_RE.subn(f'color_theme = "{theme}"', original)
    if count == 0:
        warning(f"No color_theme line in {CONF}; launching with existing theme")
        return

    if updated != original:
        try:
            with CONF.open("w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
                handle.write(updated)
        except OSError as exc:
            warning(f"Could not write {CONF}: {exc}; launching with existing theme")
            return

    info(f"btop theme -> {theme}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    # Theme first, then the binary check: the shell version rewrote the config
    # even when btop was missing, so re-ordering would silently stop the theme
    # tracking the system appearance on a machine where btop is not installed.
    apply_theme(current_theme())

    btop = require_binary("btop", hint="Install it with `brew install btop`.")

    # exec, not spawn: btop is a full-screen TUI and this process has nothing
    # left to do. Replacing the image keeps signal handling and the exit code
    # identical to running btop directly, exactly like `exec btop "$@"`.
    # argv[0] stays the bare name, which is what btop echoes in its own usage.
    os.execv(btop, ["btop", *args])  # noqa: S606 - absolute path, no shell
    return 0  # unreachable; execv never returns


if __name__ == "__main__":
    sys.exit(main())
