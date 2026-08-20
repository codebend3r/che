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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    info,
    log,
    note,
    require_binary,
    run,
    run_cli,
    success,
    warning,
)

__version__ = "1.0.0"


def brew(
    argv: list[str],
    *,
    dry_run: bool,
    dry_run_argv: list[str] | None = None,
    echo: bool = False,
) -> None:
    """Run a brew subcommand, or its --dry-run form.

    Homebrew's own ``--dry-run`` exits non-zero in some situations that are not
    really failures, so the preview calls are non-fatal - the same ``|| true``
    the shell version used. The real calls stay fatal.
    """
    if dry_run:
        if dry_run_argv is None:
            warning(f"  🪄 Would run: {' '.join(argv)}")
            return
        run(dry_run_argv, check=False)
        return

    # Only `brew update` echoed its command in the shell version; the other
    # steps called brew directly, and brew narrates itself.
    if echo:
        log(f"  ▶ {' '.join(argv)}")
    run(argv)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="update-brew",
        description="🍺 Update Homebrew, upgrade formulae and casks, then clean up.",
    )
    add_bool_flag(parser, "--dry-run", help="Show what would change, change nothing")
    add_bool_flag(parser, "--no-cask", dest="no_cask", help="Skip upgrading casks")
    add_bool_flag(parser, "--no-cleanup", dest="no_cleanup", help="Skip 'brew cleanup'")
    add_bool_flag(parser, "--no-autoremove", dest="no_autoremove", help="Skip 'brew autoremove'")
    add_bool_flag(parser, "--greedy", help="Pass --greedy to cask upgrade")
    add_bool_flag(parser, "--doctor", help="Run 'brew doctor' at the very end")
    args = parser.parse_args(argv)

    require_binary("brew", hint="Install Homebrew first: https://brew.sh")

    dry = args.dry_run
    header_suffix = " 🌵 (dry run)" if dry else ""
    note("═══════════════════════════════════════════")
    note(f"🍺  update-brew{header_suffix}")
    note("═══════════════════════════════════════════")

    # 1. Refresh Homebrew itself and tap metadata
    info("📡 Updating Homebrew metadata...")
    brew(["brew", "update"], dry_run=dry, echo=True)

    # 2. Upgrade formulae
    info("⬆️  Upgrading formulae...")
    brew(["brew", "upgrade"], dry_run=dry, dry_run_argv=["brew", "upgrade", "--dry-run"])

    # 3. Upgrade casks (apps)
    if args.no_cask:
        note("⏭️  Skipping cask upgrades (--no-cask)")
    else:
        info("📦 Upgrading casks...")
        cask_argv = ["brew", "upgrade", "--cask"]
        if args.greedy:
            cask_argv.append("--greedy")
        brew(cask_argv, dry_run=dry, dry_run_argv=[*cask_argv, "--dry-run"])

    # 4. Remove unused dependencies
    if args.no_autoremove:
        note("⏭️  Skipping autoremove (--no-autoremove)")
    else:
        info("🧹 Removing unused dependencies...")
        brew(
            ["brew", "autoremove"],
            dry_run=dry,
            dry_run_argv=["brew", "autoremove", "--dry-run"],
        )

    # 5. Cleanup old versions + cache
    if args.no_cleanup:
        note("⏭️  Skipping cleanup (--no-cleanup)")
    else:
        info("🗑️  Cleaning up old versions and cache...")
        brew(
            ["brew", "cleanup", "-s"],
            dry_run=dry,
            dry_run_argv=["brew", "cleanup", "--dry-run", "-s"],
        )

    # 6. Optional doctor pass - advisory, never fatal
    if args.doctor:
        info("🩺 Running brew doctor...")
        completed = run(["brew", "doctor"], check=False)
        if completed.returncode != 0:
            warning("⚠️  brew doctor reported issues (non-fatal)")

    print()
    note("─────────────────────────────────────────────")
    if dry:
        log("💡 Dry run complete. Nothing was actually changed.")
    else:
        success("🎉 Homebrew is up to date and tidy! 🍺✨")
    return 0


if __name__ == "__main__":
    run_cli(main)
