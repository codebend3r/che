#!/usr/bin/env python3
"""🍺 Update Homebrew, upgrade formulae and casks, then clean up.

Usage:
  update-brew.py [--dry-run] [--no-cask] [--no-cleanup] [--no-autoremove]
                 [--greedy] [--doctor]

Options:
  --dry-run        Show what would be upgraded/removed, change nothing
  --no-cask        Skip upgrading casks (apps)
  --no-cleanup     Skip 'brew cleanup' at the end
  --no-autoremove  Skip 'brew autoremove' (leave unused deps in place)
  --greedy         Pass --greedy to cask upgrade (force-update self-updating apps)
  --doctor         Run 'brew doctor' at the very end
  --help           Show help
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    dry_run_complete,
    footer_rule,
    heading,
    info,
    log,
    note,
    require_binary,
    run,
    run_cli,
    success,
    warning,
)

__version__ = "1.1.0"


class Step(NamedTuple):
    """One brew command the update runs, and what skips it."""

    banner: str
    command: list[str]
    skip: str = ""  # what a passed --no-* flag skips, for the skip note


def brew(command: list[str], *, dry_run: bool) -> None:
    """Run a brew subcommand, or preview it with Homebrew's own ``--dry-run``.

    That ``--dry-run`` exits non-zero in some situations that are not really
    failures, so the preview calls are non-fatal - the same ``|| true`` the
    shell version used. The real calls stay fatal.
    """
    if dry_run:
        run([*command, "--dry-run"], check=False)
    else:
        run(command)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="update-brew",
        description="🍺 Update Homebrew, upgrade formulae and casks, then clean up.",
    )
    add_bool_flag(parser, "--dry-run", help="Show what would change, change nothing")
    # Bare spellings only, as the shell version took them: `--no-cask=false`
    # is a double negative, not a way to ask for casks.
    add_bool_flag(parser, "--no-cask", allow_value=False, help="Skip upgrading casks")
    add_bool_flag(parser, "--no-cleanup", allow_value=False, help="Skip 'brew cleanup'")
    add_bool_flag(parser, "--no-autoremove", allow_value=False, help="Skip 'brew autoremove'")
    add_bool_flag(parser, "--greedy", help="Pass --greedy to cask upgrade")
    add_bool_flag(parser, "--doctor", help="Run 'brew doctor' at the very end")
    args = parser.parse_args(argv)

    require_binary("brew", hint="Install Homebrew first: https://brew.sh")

    dry = args.dry_run
    heading("🍺  update-brew", dry_run=dry)

    # 1. Refresh Homebrew itself and tap metadata. brew has no preview for
    # this, and it is the one step whose command the shell version echoed;
    # brew narrates the others itself.
    info("📡 Updating Homebrew metadata...")
    if dry:
        warning("  🪄 Would run: brew update")
    else:
        log("  ▶ brew update")
        run(["brew", "update"])

    # 2-5.
    cask = ["brew", "upgrade", "--cask", *(["--greedy"] if args.greedy else [])]
    steps = (
        Step("⬆️  Upgrading formulae...", ["brew", "upgrade"]),
        Step("📦 Upgrading casks...", cask, "cask upgrades (--no-cask)" if args.no_cask else ""),
        Step(
            "🧹 Removing unused dependencies...",
            ["brew", "autoremove"],
            "autoremove (--no-autoremove)" if args.no_autoremove else "",
        ),
        Step(
            "🗑️  Cleaning up old versions and cache...",
            ["brew", "cleanup", "-s"],
            "cleanup (--no-cleanup)" if args.no_cleanup else "",
        ),
    )
    for step in steps:
        if step.skip:
            note(f"⏭️  Skipping {step.skip}")
            continue
        info(step.banner)
        brew(step.command, dry_run=dry)

    # 6. Optional doctor pass - advisory, never fatal
    if args.doctor:
        info("🩺 Running brew doctor...")
        completed = run(["brew", "doctor"], check=False)
        if completed.returncode != 0:
            warning("⚠️  brew doctor reported issues (non-fatal)")

    footer_rule()
    if dry:
        dry_run_complete()
    else:
        success("🎉 Homebrew is up to date and tidy! 🍺✨")
    return 0


if __name__ == "__main__":
    run_cli(main)
