#!/usr/bin/env python3
"""📡 Keep-alive pinger for the NAS drives.

Each cycle probes every host's SMB port and verifies it is still mounted under
/Volumes. The probe is a TCP connect to port 445 rather than ICMP, because the
Synology firewalls drop ICMP echo while still serving SMB.

If a drive is reachable but the share has dropped off /Volumes (eject, network
blip, sleep) it is silently remounted via AppleScript's ``mount volume`` using
Keychain credentials, with no Finder modals.

Usage:
  ping-nas.py [--interval=SECONDS] [--ping-timeout=SECONDS] [--only=NAME]
              [--no-remount] [--use-ip] [--once] [--quiet]

Options:
  --interval=N       Seconds between cycles (default: 300)
  --ping-timeout=N   Per-host ping timeout in seconds (default: 2)
  --only=NAME        Only ping the drive with this name (case-insensitive)
  --no-remount       Detect-only: warn about missing mounts, don't remount
  --use-ip           Remount via //USER@IP/NAME instead of //USER@NAME/NAME
  --once             Run a single cycle and exit (useful from cron)
  --quiet            Only log failures, remount attempts, and cycle summary
  --help             Show help
"""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nas import SMB_USER, NasDrive, is_mounted, mount_smb, select_drives, smb_url
from utils import (
    add_bool_flag,
    build_parser,
    heading,
    info,
    log,
    parse_count,
    run,
    run_cli,
    success,
    warning,
)

__version__ = "3.4.0"

SMB_PORT = 445


def smb_reachable(ip: str, timeout: int) -> bool:
    """One TCP connect to the SMB port with a per-host timeout in seconds.

    ICMP is useless here: the NAS firewalls drop echo requests, so ``ping``
    reported every drive unreachable while the shares were mounted fine. The
    probe goes through Apple's ``/usr/bin/nc`` rather than a Python socket
    because macOS Local Network privacy can deny LAN connections from a
    Homebrew Python (``EHOSTUNREACH``) while exempting system binaries.
    """
    completed = run(
        ["/usr/bin/nc", "-z", "-G", str(timeout), ip, str(SMB_PORT)],
        check=False,
        capture=True,
    )
    return completed.returncode == 0


def remount_drive(name: str, host: str) -> bool:
    """Remount one drive via AppleScript. True on success."""
    log(f"  🔗 Remounting {name} ({smb_url(name, host)})...")
    if not mount_smb(name, host):
        return False

    success(f"  ✅ {name} remounted 🐉")
    return True


def ping_all_nas(
    active: list[NasDrive],
    *,
    cycle: int,
    ping_timeout: int,
    remount: bool,
    use_ip: bool,
    quiet: bool,
) -> None:
    """Run check cycle number ``cycle`` over the active drive list."""
    unreachable = 0
    unmounted = 0
    remounted = 0
    remount_failed = 0

    if not quiet:
        log(f"🔄 Cycle #{cycle} — checking {len(active)} NAS drive(s)...")

    for drive in active:
        if not smb_reachable(drive.ip, ping_timeout):
            warning(f"  ❌ {drive.name} ({drive.ip}): SMB port {SMB_PORT} unreachable")
            unreachable += 1
            continue

        if is_mounted(drive.name):
            if not quiet:
                log(f"  ✅ 🐉 {drive.name} ({drive.ip}) — mounted")
            continue

        warning(f"  ⚠️  {drive.name} ({drive.ip}) — reachable but not mounted")
        unmounted += 1

        if remount:
            if remount_drive(drive.name, drive.host(use_ip=use_ip)):
                remounted += 1
            else:
                remount_failed += 1

    if unreachable == 0 and unmounted == 0:
        if not quiet:
            success(f"✨ All {len(active)} drive(s) responded and mounted 🎉")
        return

    parts = []
    if unreachable:
        parts.append(f"{unreachable} unreachable")
    if remounted:
        parts.append(f"{remounted} remounted")
    if remount_failed:
        parts.append(f"{remount_failed} remount-failed")
    if not remount and unmounted:
        parts.append(f"{unmounted} unmounted")
    warning(f"⚠️  Cycle summary: {' '.join(parts)}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="ping-nas",
        description="📡 Keep-alive pinger for the NAS drives.",
        epilog=(
            f"Each cycle probes every host's SMB port ({SMB_PORT}) and verifies it is\n"
            "still mounted under /Volumes. A drive that is reachable but has\n"
            "dropped off /Volumes is silently remounted via AppleScript as\n"
            f"'{SMB_USER}' using Keychain credentials, with no Finder modals."
        ),
    )
    # Strings, validated by parse_count below rather than `type=int`.
    parser.add_argument(
        "--interval", default="300", metavar="N", help="Seconds between cycles (default: 300)"
    )
    parser.add_argument(
        "--ping-timeout",
        default="2",
        metavar="N",
        help="Per-host ping timeout in seconds (default: 2)",
    )
    parser.add_argument(
        "--only", default="", metavar="NAME", help="Only ping this drive (case-insensitive)"
    )
    add_bool_flag(
        parser,
        "--no-remount",
        allow_value=False,
        help="Detect-only: warn about missing mounts, don't remount",
    )
    add_bool_flag(parser, "--use-ip", help="Remount via //USER@IP/NAME instead of //USER@NAME/NAME")
    add_bool_flag(parser, "--once", help="Run a single cycle and exit (useful from cron)")
    add_bool_flag(parser, "--quiet", help="Only log failures, remount attempts, and cycle summary")
    args = parser.parse_args(argv)

    interval = parse_count(args.interval, "--interval", minimum=1)
    ping_timeout = parse_count(args.ping_timeout, "--ping-timeout", minimum=1)

    active = select_drives(args.only)
    if not active:
        warning(f"❌ No drives matched --only={args.only}")
        return 1

    # INT and TERM both stop the pinger with exit 0, matching the shell
    # version's trap. SIGINT is set too, not left to Python's default, because
    # a pinger started in the background by a script inherits it ignored.
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, signal.default_int_handler)
    cycle = 0
    try:
        heading("📡  ping-nas")
        if not args.once:
            info(
                f"🚀 Keep-alive pinger started for {len(active)} NAS "
                f"(every {interval}s). Press Ctrl-C to stop."
            )

        while True:
            cycle += 1
            ping_all_nas(
                active,
                cycle=cycle,
                ping_timeout=ping_timeout,
                remount=not args.no_remount,
                use_ip=args.use_ip,
                quiet=args.quiet,
            )
            if args.once:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        print()
        info(f"👋 Stopping keep-alive pinger after {cycle} cycle(s).")
        return 0


if __name__ == "__main__":
    run_cli(main)
