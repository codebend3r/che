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
from typing import NamedTuple

from utils import run, warning

SMB_USER = "crivas"


class NasDrive(NamedTuple):
    """One NAS. The share name is assumed to match the drive name, so
    //crivas@Meleys/Meleys mounts at /Volumes/Meleys."""

    name: str
    ip: str

    def host(self, *, use_ip: bool) -> str:
        """How to reach it in a share URL: by IP under ``--use-ip``, else by name."""
        return self.ip if use_ip else self.name


NAS_DRIVES: tuple[NasDrive, ...] = (
    NasDrive("Meleys", "192.168.50.2"),
    NasDrive("Vermithor", "192.168.50.3"),
    NasDrive("Caraxes", "192.168.50.4"),
    NasDrive("Syrax", "192.168.50.5"),
    NasDrive("Vhagar", "192.168.50.6"),
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


def is_mounted(name: str) -> bool:
    """True when something is actually mounted at ``/Volumes/<name>``.

    The shell version grepped ``mount`` output for `` on /Volumes/<name> (``;
    ``os.path.ismount`` asks the kernel directly. The two agree for every
    healthy mount. The one real difference: ``ismount`` lstats the mount root,
    so on a wedged SMB mount it can block for the server timeout where reading
    the mount table cannot.
    """
    return os.path.ismount(f"/Volumes/{name}")


def smb_url(name: str, host: str) -> str:
    """The share URL for drive ``name``, reached at ``host`` (its name or its IP)."""
    return f"smb://{SMB_USER}@{host}/{name}"


def mount_smb(name: str, host: str) -> bool:
    """Mount one share via AppleScript's ``mount volume``. True on success.

    AppleScript rather than ``mount_smbfs`` takes the same NetAuth path Finder
    does: ``/Volumes/<name>`` is created automatically and Keychain credentials
    are used silently, with no Finder modals. On failure this prints why; the
    caller prints its own progress and success lines.
    """
    url = smb_url(name, host)
    completed = run(["osascript", "-e", f'mount volume "{url}"'], check=False, capture=True)
    if completed.returncode == 0:
        return True

    warning(f"  ❌ mount failed for {url}")
    stderr = (completed.stderr or "").strip()
    if stderr:
        warning(f"     {stderr}")
    warning(f"     Check that Keychain has a password for '{SMB_USER}@{host}'.")
    return False
