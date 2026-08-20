#!/usr/bin/env python3
"""📤 Eject all NAS volumes from /Volumes.

Checks the primary mount as well as the duplicate ``<name>-1`` and IP-named
mounts macOS creates when it re-mounts the same share twice. Stale placeholder
directories left behind by a force-unmount are cleaned up with rmdir (sudo as a
fallback).

Also resets Finder's Favorite Servers and Recent Hosts lists, otherwise ejected
NAS shares keep reappearing in the sidebar Locations after Finder relaunches.

Usage:
  eject-all-drives.py [--dry-run] [--only=NAME] [--no-force]
                      [--no-clear-favorites] [--quiet]

Options:
  --dry-run              Show what would be unmounted, change nothing
  --only=NAME            Only eject this drive (case-insensitive); skips the
                         Favorite Servers reset, which would be over-broad
  --no-force             Use 'diskutil unmount' instead of 'diskutil unmount force'
  --no-clear-favorites   Don't reset Finder's Favorite Servers / Recent Hosts
  --quiet                Only log unmounts and failures
  --help                 Show help
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

__version__ = "3.3.0"

DRIVES: tuple[tuple[str, str], ...] = (
    ("Meleys", "192.168.50.2"),
    ("Vermithor", "192.168.50.3"),
    ("Caraxes", "192.168.50.4"),
    ("Syrax", "192.168.50.5"),
    ("Vhagar", "192.168.50.6"),
)


def eject_volume(label: str, *, dry_run: bool, force: bool, quiet: bool) -> str:
    """Unmount ``/Volumes/<label>``. Returns "ejected", "skipped" or "failed"."""
    mount = Path("/Volumes") / label

    if not mount.is_dir():
        if not quiet:
            info(f"  ⏭️  {label} — not mounted")
        return "skipped"

    if dry_run:
        warning(f"  🪄 Would unmount {mount}")
        return "ejected"

    unmount_cmd = ["diskutil", "unmount"]
    if force:
        unmount_cmd.append("force")

    log(f"  📤 Unmounting {mount}...")
    completed = run([*unmount_cmd, str(mount)], check=False, capture=True)
    if completed.returncode != 0:
        warning(f"  ❌ Failed to unmount {mount}")
        return "failed"

    # A force-unmount can leave the placeholder directory behind. Try to clear
    # it unprivileged first; fall back to sudo, and give up quietly if neither
    # works, exactly as the shell version did.
    if mount.is_dir():
        try:
            mount.rmdir()
        except OSError:
            run(["sudo", "rmdir", str(mount)], check=False, capture=True)

    success(f"  ✅ {label} ejected")
    return "ejected"


def reset_finder_state(
    selected: list[tuple[str, str]], *, clear_favorites: bool, only: str
) -> None:
    """Drop Finder's server-level entries so the sidebar stops resurrecting them."""
    log("🪪 Asking Finder to drop any server-level entries...")
    for name, _ in selected:
        run(
            [
                "osascript",
                "-e",
                'tell application "Finder" to try',
                "-e",
                f'eject disk "{name}"',
                "-e",
                "end try",
            ],
            check=False,
            capture=True,
        )

    # Skipped when --only is set: resetlist is all-or-nothing and would nuke
    # the other drives' favorites too.
    if not only and clear_favorites:
        log("🧽 Resetting Finder Favorite Servers + Recent Hosts lists...")
        for list_name in (
            "com.apple.LSSharedFileList.FavoriteServers",
            "com.apple.LSSharedFileList.RecentHosts",
        ):
            run(["sfltool", "resetlist", list_name], check=False, capture=True)

    # SIGKILL specifically: a graceful quit lets Finder save its current
    # sidebar state on the way out and restore the stale entries on relaunch.
    log("🔄 Hard-killing Finder so it doesn't restore stale sidebar state...")
    run(["killall", "-KILL", "Finder"], check=False, capture=True)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="eject-all-drives",
        description="📤 Eject all NAS volumes from /Volumes.",
    )
    add_bool_flag(parser, "--dry-run", help="Show what would be unmounted, change nothing")
    parser.add_argument(
        "--only", default="", metavar="NAME", help="Only eject this drive (case-insensitive)"
    )
    add_bool_flag(
        parser,
        "--no-force",
        dest="no_force",
        allow_value=False,
        help="Use 'diskutil unmount' instead of 'diskutil unmount force'",
    )
    add_bool_flag(
        parser,
        "--no-clear-favorites",
        dest="no_clear_favorites",
        allow_value=False,
        help="Don't reset Finder's Favorite Servers / Recent Hosts lists",
    )
    add_bool_flag(parser, "--quiet", help="Only log unmounts and failures")
    args = parser.parse_args(argv)

    force = not args.no_force
    clear_favorites = not args.no_clear_favorites

    # Only gate on diskutil for a real run: the shell version's dry-run never
    # invoked it, so previewing worked anywhere.
    if not args.dry_run:
        require_binary("diskutil", hint="This script is macOS-only.")

    header_suffix = " 🌵 (dry run)" if args.dry_run else ""
    note("═══════════════════════════════════════════")
    note(f"📤  eject-all-drives{header_suffix}")
    note("═══════════════════════════════════════════")

    selected = [(n, ip) for n, ip in DRIVES if not args.only or n.lower() == args.only.lower()]
    if args.only and not selected:
        # Warn, but keep the shell version's exit code and control flow: an
        # unknown --only printed a 0/0 summary and still exited 0.
        warning(f"⚠️  No drive named '{args.only}'. Known: {', '.join(n for n, _ in DRIVES)}")

    counts = {"ejected": 0, "skipped": 0, "failed": 0}

    for name, ip in selected:
        info(f"🐉 {name} ({ip})")
        # macOS re-mounts of the same share land at "<name>-1" or at the IP.
        for label in (name, f"{name}-1", ip):
            counts[eject_volume(label, dry_run=args.dry_run, force=force, quiet=args.quiet)] += 1

    print()
    note("─────────────────────────────────────────────")

    if args.dry_run:
        success(f"🌵 Would eject:  {counts['ejected']}")
        info(f"⏭️  Skipped:     {counts['skipped']} (not mounted)")
        log("💡 Dry run complete. Nothing was actually ejected.")
        return 0

    success(f"✅ Ejected:  {counts['ejected']}")
    info(f"⏭️  Skipped:  {counts['skipped']} (not mounted)")
    if counts["failed"]:
        warning(f"❌ Failed:   {counts['failed']}")
        return 1

    reset_finder_state(selected, clear_favorites=clear_favorites, only=args.only)
    log("🎉 All clean! 🧹✨")
    return 0


if __name__ == "__main__":
    run_cli(main)
