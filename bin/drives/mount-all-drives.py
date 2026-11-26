#!/usr/bin/env python3
"""💿 Mount all NAS drives over SMB via AppleScript's ``mount volume``.

Using AppleScript (rather than ``mount_smbfs``) takes the same NetAuth path
Finder does, so ``/Volumes/<name>`` is created automatically and Keychain
credentials are used silently, with no Finder modals. Already-mounted drives
are skipped. Each share is named after its drive, e.g.
``//crivas@Meleys/Meleys`` → ``/Volumes/Meleys``.

Usage:
  mount-all-drives.py [--only=NAME] [--use-ip] [--quiet]

Options:
  --only=NAME   Only mount the drive with this name (case-insensitive)
  --use-ip      Mount via //USER@IP/NAME instead of //USER@NAME/NAME
  --quiet       Only log mounts and failures
  --help        Show help
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nas import SMB_USER, NasDrive, is_mounted, mount_smb, select_drives, warn_unknown_drive
from report import FAIL, OK, SAME, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    heading,
    log,
    require_binary,
    run_cli,
    warning,
)

__version__ = "5.2.1"


class Mount(Outcome):
    """Everything a mount can conclude about a drive, in summary order."""

    MOUNTED = (OK, "mounted", "Mounted")
    ALREADY = (SAME, "", "Already mounted", Listing.COUNT)
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


def mount_drive(tally: Tally[Mount], drive: NasDrive, *, use_ip: bool) -> None:
    """Mount one drive and record how it went."""
    name = drive.name
    if is_mounted(drive.name):
        tally.record(Mount.ALREADY, name)
        return

    url = drive.mount_url(use_ip=use_ip)
    if reason := mount_smb(url):
        tally.record(Mount.FAILED, name, f"{url}: {reason}", item=f"{name}: {reason}")
        return
    tally.record(Mount.MOUNTED, name, url)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="mount-all-drives",
        description="💿 Mount all NAS drives over SMB via AppleScript.",
    )
    parser.add_argument(
        "--only", default="", metavar="NAME", help="Only mount this drive (case-insensitive)"
    )
    add_bool_flag(parser, "--use-ip", help="Mount via //USER@IP/NAME instead of //USER@NAME/NAME")
    add_bool_flag(parser, "--quiet", help="Only log mounts and failures")
    args = parser.parse_args(argv)
    started = time.monotonic()

    require_binary("osascript", hint="This script is macOS-only.")

    heading("💿  mount-all-drives")

    selected = select_drives(args.only)
    if not selected:
        warn_unknown_drive(args.only)

    # --quiet is still accepted, but has nothing left to hide: an already
    # mounted drive (all it used to silence) is now only counted in the summary.
    tally = Tally(Mount)
    with tally.progress(len(selected)) as progress:
        for drive in selected:
            progress.step(drive.name)
            mount_drive(tally, drive, use_ip=args.use_ip)

    failed = tally.count(Mount.FAILED)
    notes = []
    if failed:
        notes.append(f"Check that Keychain has a password for {SMB_USER} on each failed host.")
    tally.summary(
        "Summary",
        facts=[plural(len(selected), "drive"), duration(time.monotonic() - started)],
        notes=notes,
    )
    print()
    if failed:
        warning(f"⚠️  {plural(failed, 'drive')} failed to mount. Every other drive was still tried.")
        return 1

    log("🎉 All drives are up! 🐉🐉🐉")
    return 0


if __name__ == "__main__":
    run_cli(main)
