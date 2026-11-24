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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nas import NasDrive, select_drives, warn_unknown_drive
from report import FAIL, OK, PLAN, SAME, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    dry_run_complete,
    heading,
    log,
    require_binary,
    run,
    run_cli,
    warning,
)

__version__ = "4.1.0"


class Eject(Outcome):
    """Everything an eject can conclude about a volume, in summary order."""

    EJECTED = (OK, "ejected", "Ejected")
    WOULD_EJECT = (PLAN, "would eject", "Would eject")
    NOT_MOUNTED = (SAME, "", "Not mounted", Listing.COUNT)
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


def eject_volume(tally: Tally[Eject], label: str, *, dry_run: bool, force: bool) -> None:
    """Unmount ``/Volumes/<label>`` and record how it went."""
    mount = Path("/Volumes") / label

    if not mount.is_dir():
        tally.record(Eject.NOT_MOUNTED, label)
        return

    if dry_run:
        tally.record(Eject.WOULD_EJECT, label)
        return

    unmount_cmd = ["diskutil", "unmount"]
    if force:
        unmount_cmd.append("force")

    completed = run([*unmount_cmd, str(mount)], check=False, capture=True)
    if completed.returncode != 0:
        reason = (completed.stderr or "").strip() or "diskutil unmount failed"
        tally.record(Eject.FAILED, label, reason, item=f"{label}: {reason}")
        return

    # A force-unmount can leave the placeholder directory behind. Try to clear
    # it unprivileged first; fall back to sudo, and give up quietly if neither
    # works, exactly as the shell version did.
    if mount.is_dir():
        try:
            mount.rmdir()
        except OSError:
            run(["sudo", "rmdir", str(mount)], check=False, capture=True)

    tally.record(Eject.EJECTED, label)


def reset_finder_state(selected: list[NasDrive], *, reset_lists: bool) -> None:
    """Drop Finder's server-level entries so the sidebar stops resurrecting them."""
    log("🪪 Asking Finder to drop any server-level entries...")
    for drive in selected:
        run(
            [
                "osascript",
                "-e",
                'tell application "Finder" to try',
                "-e",
                f'eject disk "{drive.volume}"',
                "-e",
                "end try",
            ],
            check=False,
            capture=True,
        )

    if reset_lists:
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
        allow_value=False,
        help="Use 'diskutil unmount' instead of 'diskutil unmount force'",
    )
    add_bool_flag(
        parser,
        "--no-clear-favorites",
        allow_value=False,
        help="Don't reset Finder's Favorite Servers / Recent Hosts lists",
    )
    add_bool_flag(parser, "--quiet", help="Only log unmounts and failures")
    args = parser.parse_args(argv)
    started = time.monotonic()

    # Only gate on diskutil for a real run: the shell version's dry-run never
    # invoked it, so previewing worked anywhere.
    if not args.dry_run:
        require_binary("diskutil", hint="This script is macOS-only.")

    heading("📤  eject-all-drives", dry_run=args.dry_run)

    selected = select_drives(args.only)
    if not selected:
        warn_unknown_drive(args.only)

    force = not args.no_force
    # macOS re-mounts of the same share land at "<share>-1" or at the IP.
    labels = [label for d in selected for label in (d.volume, f"{d.volume}-1", d.ip)]

    # --quiet is still accepted, but has nothing left to hide: a volume that is
    # not mounted (all it used to silence) is now only counted in the summary.
    tally = Tally(Eject)
    with tally.progress(len(labels)) as progress:
        for label in labels:
            progress.step(label)
            eject_volume(tally, label, dry_run=args.dry_run, force=force)

    failed = tally.count(Eject.FAILED)
    if not args.dry_run and not failed:
        # The lists are left alone under --only: resetlist is all-or-nothing and
        # would nuke the other drives' favorites too.
        print()
        reset_finder_state(selected, reset_lists=not args.only and not args.no_clear_favorites)

    tally.summary(
        "Preview" if args.dry_run else "Summary",
        facts=[plural(len(selected), "drive"), duration(time.monotonic() - started)],
    )
    print()
    if failed:
        warning(f"⚠️  {plural(failed, 'volume')} failed to unmount; Finder was left alone.")
        return 1
    if args.dry_run:
        dry_run_complete("ejected")
    else:
        log("🎉 All clean! 🧹✨")
    return 0


if __name__ == "__main__":
    run_cli(main)
