#!/usr/bin/env python3
"""💿 Mount all NAS drives over SMB via AppleScript's ``mount volume``.

Using AppleScript (rather than ``mount_smbfs``) takes the same NetAuth path
Finder does, so ``/Volumes/<name>`` is created automatically and Keychain
credentials are used silently, with no Finder modals. Already-mounted drives
are skipped. The share name is assumed to match the drive name, e.g.
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nas import is_mounted, mount_smb, select_drives, smb_url, warn_unknown_drive
from utils import (
    add_bool_flag,
    build_parser,
    footer_rule,
    heading,
    info,
    log,
    require_binary,
    run_cli,
    success,
    warning,
)

__version__ = "4.1.0"


def mount_drive(name: str, host: str, *, quiet: bool) -> str:
    """Mount one drive. Returns "mounted", "skipped" or "failed"."""
    if is_mounted(name):
        if not quiet:
            info(f"⏭️  {name} — already mounted")
        return "skipped"

    log(f"🔗 Mounting {name} ({smb_url(name, host)})...")
    if not mount_smb(name, host):
        return "failed"

    success(f"  ✅ {name} mounted 🐉")
    return "mounted"


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

    require_binary("osascript", hint="This script is macOS-only.")

    heading("💿  mount-all-drives")

    selected = select_drives(args.only)
    if not selected:
        warn_unknown_drive(args.only)

    counts = {"mounted": 0, "skipped": 0, "failed": 0}
    for drive in selected:
        host = drive.host(use_ip=args.use_ip)
        counts[mount_drive(drive.name, host, quiet=args.quiet)] += 1

    footer_rule()
    success(f"✅ Mounted:  {counts['mounted']}")
    info(f"⏭️  Skipped:  {counts['skipped']} (already mounted)")
    if counts["failed"]:
        warning(f"❌ Failed:   {counts['failed']}")
        return 1

    log("🎉 All drives are up! 🐉🐉🐉")
    return 0


if __name__ == "__main__":
    run_cli(main)
