#!/usr/bin/env python3
"""📡 Keep-alive pinger for the NAS drives.

Each cycle pings every host and verifies it is still mounted under /Volumes.
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

import os
import re
import signal
import sys
import time
from pathlib import Path
from types import FrameType

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    info,
    log,
    note,
    run,
    run_cli,
    success,
    warning,
)

__version__ = "3.3.0"

SMB_USER = "crivas"

DRIVES: tuple[tuple[str, str], ...] = (
    ("Meleys", "192.168.50.2"),
    ("Vermithor", "192.168.50.3"),
    ("Caraxes", "192.168.50.4"),
    ("Syrax", "192.168.50.5"),
    ("Vhagar", "192.168.50.6"),
)

_cycle = 0


def is_mounted(name: str) -> bool:
    """True when something is actually mounted at ``/Volumes/<name>``."""
    return os.path.ismount(f"/Volumes/{name}")


def ping_host(ip: str, timeout: int) -> bool:
    """One ICMP probe with a per-host timeout. macOS ``ping -t`` is seconds."""
    completed = run(["ping", "-c", "1", "-t", str(timeout), ip], check=False, capture=True)
    return completed.returncode == 0


def remount_drive(name: str, host: str) -> bool:
    """Remount one drive via AppleScript. True on success."""
    url = f"smb://{SMB_USER}@{host}/{name}"
    log(f"  🔗 Remounting {name} ({url})...")

    completed = run(["osascript", "-e", f'mount volume "{url}"'], check=False, capture=True)
    if completed.returncode == 0:
        success(f"  ✅ {name} remounted 🐉")
        return True

    warning(f"  ❌ mount failed for {url}")
    stderr = (completed.stderr or "").strip()
    if stderr:
        warning(f"     {stderr}")
    warning(f"     Check that Keychain has a password for '{SMB_USER}@{host}'.")
    return False


def ping_all_nas(
    active: list[tuple[str, str]],
    *,
    ping_timeout: int,
    remount: bool,
    use_ip: bool,
    quiet: bool,
) -> None:
    """Run one full check cycle over the active drive list."""
    global _cycle
    _cycle += 1

    unreachable = 0
    unmounted = 0
    remounted = 0
    remount_failed = 0

    if not quiet:
        log(f"🔄 Cycle #{_cycle} — checking {len(active)} NAS drive(s)...")

    for name, ip in active:
        if not ping_host(ip, ping_timeout):
            warning(f"  ❌ {name} ({ip}) — ping failed")
            unreachable += 1
            continue

        if is_mounted(name):
            if not quiet:
                log(f"  ✅ 🐉 {name} ({ip}) — mounted")
            continue

        warning(f"  ⚠️  {name} ({ip}) — reachable but not mounted")
        unmounted += 1

        if remount:
            if remount_drive(name, ip if use_ip else name):
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


def _shutdown(signum: int, frame: FrameType | None) -> None:
    """Exit 0 on Ctrl-C, matching the shell version's INT/TERM trap."""
    print()
    info(f"👋 Stopping keep-alive pinger after {_cycle} cycle(s).")
    sys.exit(0)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="ping-nas",
        description="📡 Keep-alive pinger for the NAS drives.",
        epilog=(
            "Each cycle pings every host and verifies it is still mounted under\n"
            "/Volumes. A drive that is reachable but has dropped off /Volumes is\n"
            f"silently remounted via AppleScript as '{SMB_USER}' using Keychain\n"
            "credentials, with no Finder modals."
        ),
    )
    # --interval and --ping-timeout stay strings so the shell version's own
    # message survives; `type=int` would let argparse own the failure first.
    parser.add_argument(
        "--interval", default="300", metavar="N", help="Seconds between cycles (default: 300)"
    )
    parser.add_argument(
        "--ping-timeout",
        dest="ping_timeout",
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
        dest="no_remount",
        allow_value=False,
        help="Detect-only: warn about missing mounts, don't remount",
    )
    add_bool_flag(
        parser,
        "--use-ip",
        dest="use_ip",
        help="Remount via //USER@IP/NAME instead of //USER@NAME/NAME",
    )
    add_bool_flag(parser, "--once", help="Run a single cycle and exit (useful from cron)")
    add_bool_flag(parser, "--quiet", help="Only log failures, remount attempts, and cycle summary")
    args = parser.parse_args(argv)

    values: dict[str, int] = {}
    for flag, raw in (("--interval", args.interval), ("--ping-timeout", args.ping_timeout)):
        if not re.fullmatch(r"[0-9]+", raw) or int(raw) < 1:
            warning(f"❌ {flag} must be a positive integer (got: {raw})")
            return 1
        values[flag] = int(raw)
    interval = values["--interval"]
    ping_timeout = values["--ping-timeout"]

    active = [(n, ip) for n, ip in DRIVES if not args.only or n.lower() == args.only.lower()]
    if not active:
        warning(f"❌ No drives matched --only={args.only}")
        return 1

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    note("═══════════════════════════════════════════")
    note("📡  ping-nas")
    note("═══════════════════════════════════════════")

    cycle_kwargs = {
        "ping_timeout": ping_timeout,
        "remount": not args.no_remount,
        "use_ip": args.use_ip,
        "quiet": args.quiet,
    }

    if args.once:
        ping_all_nas(active, **cycle_kwargs)
        return 0

    info(
        f"🚀 Keep-alive pinger started for {len(active)} NAS "
        f"(every {interval}s). Press Ctrl-C to stop."
    )

    while True:
        ping_all_nas(active, **cycle_kwargs)
        time.sleep(interval)


if __name__ == "__main__":
    run_cli(main)
