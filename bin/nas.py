"""The NAS drive table and SMB mount helpers for the scripts under ``bin/drives/``.

Split out of the three drive scripts, which each carried their own copy of the
table, the mount check and the AppleScript mount call. Scripts pick it up the
same way as ``utils.py``::

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from nas import mount_smb, select_drives

Standard library only, like everything else at the ``bin/`` root. ``osascript``
is macOS-only; callers check for it with ``require_binary``.
"""

from __future__ import annotations

import os
import socket
import subprocess
from typing import NamedTuple

from utils import run, warning

SMB_USER = "crivas"
MOUNT_TIMEOUT = 30.0


class NasDrive(NamedTuple):
    """One NAS. The share name matches the drive name unless ``share`` says
    otherwise, so //crivas@Meleys/Meleys mounts at /Volumes/Meleys."""

    name: str
    ip: str
    share: str = ""

    @property
    def volume(self) -> str:
        """The share to mount, which is also its name under ``/Volumes``."""
        return self.share or self.name

    def url(self, *, use_ip: bool) -> str:
        """Its share URL, reaching the NAS by IP under ``--use-ip``, else by name."""
        return f"smb://{SMB_USER}@{self.ip if use_ip else self.name}/{self.volume}"

    def mount_url(self, *, use_ip: bool) -> str:
        """The URL to mount: by name, unless the name does not resolve.

        Divergence from :meth:`url`: Balerion (a UGREEN box) does not advertise
        its name the way the Synology boxes do, so ``smb://...@Balerion`` made
        ``mount volume`` hang. A name that fails to resolve falls back to the IP.
        """
        return self.url(use_ip=use_ip or not resolves(self.name))


def resolves(host: str) -> bool:
    """Whether ``host`` resolves to an address right now."""
    try:
        socket.gethostbyname(host)
    except OSError:
        return False
    return True


NAS_DRIVES: tuple[NasDrive, ...] = (
    NasDrive("Meleys", "192.168.50.2"),
    NasDrive("Vermithor", "192.168.50.3"),
    NasDrive("Caraxes", "192.168.50.4"),
    NasDrive("Syrax", "192.168.50.5"),
    NasDrive("Vhagar", "192.168.50.6"),
    # A UGREEN box, not a Synology, but it shares a folder named after itself too.
    NasDrive("Balerion", "192.168.50.234"),
)


def select_drives(only: str) -> list[NasDrive]:
    """The drives an ``--only`` value picks: all of them when it is empty.

    The match is case-insensitive. An unknown name selects nothing; see
    :func:`warn_unknown_drive`.
    """
    return [drive for drive in NAS_DRIVES if not only or drive.name.lower() == only.lower()]


def warn_unknown_drive(only: str) -> None:
    """Warn that ``--only`` named no drive, for the scripts that carry on.

    Only a warning, keeping the shell versions' exit code: an unknown --only
    printed a 0/0 summary and still exited 0. ``ping-nas`` alone refuses one.
    """
    known = ", ".join(drive.name for drive in NAS_DRIVES)
    warning(f"⚠️  No drive named '{only}'. Known: {known}")


def is_mounted(volume: str) -> bool:
    """True when something is actually mounted at ``/Volumes/<volume>``.

    The shell version grepped ``mount`` output for `` on /Volumes/<volume> (``;
    ``os.path.ismount`` asks the kernel directly. The two agree for every
    healthy mount. The one real difference: ``ismount`` lstats the mount root,
    so on a wedged SMB mount it can block for the server timeout where reading
    the mount table cannot.
    """
    return os.path.ismount(f"/Volumes/{volume}")


def mount_smb(url: str) -> str:
    """Mount the share at ``url`` via AppleScript's ``mount volume``.

    Returns "" on success, otherwise why it failed in one line (osascript's
    error), so the caller can report it as a single event. AppleScript rather
    than ``mount_smbfs`` takes the same NetAuth path Finder does:
    ``/Volumes/<share>`` is created automatically and Keychain credentials are
    used silently, with no Finder modals.
    """
    try:
        completed = run(
            ["osascript", "-e", f'mount volume "{url}"'],
            check=False,
            capture=True,
            timeout=MOUNT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        # Divergence: AppleScript has no timeout of its own and can wait forever
        # on an unreachable host, so the whole run used to stall on one drive.
        return f"timed out after {MOUNT_TIMEOUT:.0f}s"
    if completed.returncode == 0:
        return ""
    return (completed.stderr or "").strip() or "mount volume failed"
