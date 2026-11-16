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
import time
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from report import NOTE, OK, PLAN, WARN, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    dry_run_complete,
    heading,
    info,
    log,
    require_binary,
    run,
    run_cli,
)

__version__ = "2.0.0"


class Run(Outcome):
    """What became of each brew command, in summary order.

    brew narrates its own progress beneath each step's banner, so a step that
    ran or was previewed is counted silently and named in the summary; only a
    skipped step or a doctor warning gets a line of its own.
    """

    RAN = (OK, "", "Ran")
    PREVIEWED = (PLAN, "", "Previewed")
    WOULD_RUN = (PLAN, "would run", "Would run")
    SKIPPED = (NOTE, "skipped", "Skipped")
    ISSUES = (WARN, "warned", "Reported issues")


class Step(NamedTuple):
    """One brew command the update runs, and what skips it."""

    banner: str
    command: list[str]
    skip: str = ""  # the --no-* flag that skips it, if passed


def brew(command: list[str], *, dry_run: bool) -> None:
    """Run a brew subcommand, or preview it with Homebrew's own ``--dry-run``.

    That ``--dry-run`` exits non-zero in some situations that are not really
    failures, so the preview calls are non-fatal (the same ``|| true`` the
    shell version used). The real calls stay fatal.
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
    started = time.monotonic()
    heading("🍺  update-brew", dry_run=dry)
    tally = Tally(Run)

    # 1. Refresh Homebrew itself and tap metadata. brew has no preview for
    # this, and it is the one step whose command the shell version echoed;
    # brew narrates the others itself.
    info("📡 Updating Homebrew metadata...")
    if dry:
        tally.record(Run.WOULD_RUN, "brew update", "brew has no preview for it")
    else:
        log("  ▶ brew update")
        run(["brew", "update"])
        tally.record(Run.RAN, "brew update")

    # 2-5.
    cask = ["brew", "upgrade", "--cask", *(["--greedy"] if args.greedy else [])]
    steps = (
        Step("⬆️  Upgrading formulae...", ["brew", "upgrade"]),
        Step("📦 Upgrading casks...", cask, "--no-cask" if args.no_cask else ""),
        Step(
            "🧹 Removing unused dependencies...",
            ["brew", "autoremove"],
            "--no-autoremove" if args.no_autoremove else "",
        ),
        Step(
            "🗑️  Cleaning up old versions and cache...",
            ["brew", "cleanup", "-s"],
            "--no-cleanup" if args.no_cleanup else "",
        ),
    )
    for step in steps:
        name = " ".join(step.command)
        if step.skip:
            tally.record(Run.SKIPPED, name, step.skip, item=f"{name}: {step.skip}")
            continue
        info(step.banner)
        brew(step.command, dry_run=dry)
        tally.record(Run.PREVIEWED if dry else Run.RAN, name)

    # 6. Optional doctor pass: advisory, never fatal
    if args.doctor:
        info("🩺 Running brew doctor...")
        completed = run(["brew", "doctor"], check=False)
        if completed.returncode != 0:
            tally.record(Run.ISSUES, "brew doctor", "non-fatal", item="brew doctor: non-fatal")
        else:
            tally.record(Run.RAN, "brew doctor")

    commands = sum(len(entries) for entries in tally.results.values())
    tally.summary(
        "Preview" if dry else "Summary",
        facts=[plural(commands, "command"), duration(time.monotonic() - started)],
    )
    print()
    if dry:
        dry_run_complete()
    else:
        log("🎉 Homebrew is up to date and tidy! 🍺✨")
    return 0


if __name__ == "__main__":
    run_cli(main)
