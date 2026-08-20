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

import os
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

__version__ = "4.1.0"

SMB_USER = "crivas"

# (name, ip) - the share name is assumed to match the drive name.
DRIVES: tuple[tuple[str, str], ...] = (
    ("Meleys", "192.168.50.2"),
    ("Vermithor", "192.168.50.3"),
    ("Caraxes", "192.168.50.4"),
    ("Syrax", "192.168.50.5"),
    ("Vhagar", "192.168.50.6"),
)


def is_mounted(name: str) -> bool:
    """True when something is actually mounted at ``/Volumes/<name>``.

    The shell version grepped ``mount`` output for `` on /Volumes/<name> (``;
    ``os.path.ismount`` asks the kernel directly. The two agree for every
    healthy mount. The one real difference: ``ismount`` lstats the mount root,
    so on a wedged SMB mount it can block for the server timeout where reading
    the mount table cannot.
    """
    return os.path.ismount(f"/Volumes/{name}")


def mount_drive(name: str, host: str, *, quiet: bool) -> str:
    """Mount one drive. Returns "mounted", "skipped" or "failed"."""
    if is_mounted(name):
        if not quiet:
            info(f"⏭️  {name} — already mounted")
        return "skipped"

    url = f"smb://{SMB_USER}@{host}/{name}"
    log(f"🔗 Mounting {name} ({url})...")

    completed = run(
        ["osascript", "-e", f'mount volume "{url}"'],
        check=False,
        capture=True,
    )
    if completed.returncode == 0:
        success(f"  ✅ {name} mounted 🐉")
        return "mounted"

    warning(f"  ❌ mount failed for {url}")
    stderr = (completed.stderr or "").strip()
    if stderr:
        warning(f"     {stderr}")
    warning(f"     Check that Keychain has a password for '{SMB_USER}@{host}'.")
    return "failed"


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

    note("═══════════════════════════════════════════")
    note("💿  mount-all-drives")
    note("═══════════════════════════════════════════")

    counts = {"mounted": 0, "skipped": 0, "failed": 0}
    matched = False

    for name, ip in DRIVES:
        if args.only and name.lower() != args.only.lower():
            continue
        matched = True
        host = ip if args.use_ip else name
        counts[mount_drive(name, host, quiet=args.quiet)] += 1

    if args.only and not matched:
        # Warn, but keep the shell version's exit code: an unknown --only
        # printed a 0/0 summary and still exited 0.
        warning(f"⚠️  No drive named '{args.only}'. Known: {', '.join(n for n, _ in DRIVES)}")

    print()
    note("─────────────────────────────────────────────")
    success(f"✅ Mounted:  {counts['mounted']}")
    info(f"⏭️  Skipped:  {counts['skipped']} (already mounted)")
    if counts["failed"]:
        warning(f"❌ Failed:   {counts['failed']}")
        return 1

    log("🎉 All drives are up! 🐉🐉🐉")
    return 0


if __name__ == "__main__":
    run_cli(main)
