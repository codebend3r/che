#!/usr/bin/env python3
"""📦 Create a max-compression .zip of every immediate subfolder of a path.

Each ``<folder>`` becomes ``<folder>.zip`` alongside it.

Usage:
  compress-folders.py --path=/dir [--dry-run] [--verbose]

Options:
  --path=DIR    Parent directory whose subfolders should be zipped (required)
  --dry-run     Print what would be zipped, change nothing
  --verbose     Show per-file progress
  --help        Show help
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    info,
    log,
    note,
    run_cli,
    scan_root,
    success,
    warning,
)

__version__ = "3.0.0"


def _walk_entries(folder: Path) -> list[tuple[Path, str]]:
    """Every entry to store, as ``(source_path, archive_name)`` pairs.

    Symlinks are FOLLOWED, matching ``zip -r`` - which, contrary to a common
    assumption, dereferences by default and only stores links as links with
    ``-y``. Skipping them would silently drop file content from the archive.

    Directory inodes already visited are not re-entered, so a symlink loop
    cannot hang the walk. ``zip`` has its own loop protection; this is ours.
    """
    parent = folder.parent
    entries: list[tuple[Path, str]] = [(folder, str(folder.relative_to(parent)))]
    seen: set[tuple[int, int]] = set()

    for dirpath, dirnames, filenames in os.walk(folder, followlinks=True):
        directory = Path(dirpath)

        try:
            stat = directory.stat()
        except OSError:
            continue
        key = (stat.st_dev, stat.st_ino)
        if key in seen:
            dirnames[:] = []
            continue
        seen.add(key)

        dirnames.sort()
        filenames.sort()

        for name in dirnames:
            child = directory / name
            entries.append((child, str(child.relative_to(parent))))
        for name in filenames:
            child = directory / name
            entries.append((child, str(child.relative_to(parent))))

    return entries


def zip_folder(folder: Path, archive: Path, *, verbose: bool) -> None:
    """Write ``folder`` into ``archive`` with deflate level 9.

    Paths are stored relative to the folder's *parent*, so the archive expands
    to ``<folder>/...``, and the top-level directory entry is written first -
    without it an empty folder would archive to nothing at all, and its mode
    bits would be lost on restore.

    The archive is written to a temporary name and moved into place, so an
    interrupted run cannot leave a half-written .zip shadowing a good one.
    Note this always rewrites from scratch: unlike ``zip -FS`` sync mode it
    recompresses unchanged files rather than copying them across.

    Filenames are stored with the UTF-8 flag bit set, which ``zip`` does not
    do - non-ASCII names come back correctly instead of as mojibake.
    """
    temp_archive = archive.with_name(archive.name + ".partial")

    try:
        with zipfile.ZipFile(
            temp_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as zf:
            for source, arcname in _walk_entries(folder):
                if verbose and source.is_file():
                    info(f"    + {arcname}")
                zf.write(source, arcname)
        temp_archive.replace(archive)
    except BaseException:
        # Also fires on KeyboardInterrupt and SystemExit, deliberately: the
        # point is to never leave a .partial behind. Always re-raises.
        temp_archive.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="compress-folders",
        description="📦 Create a max-compression .zip of every immediate subfolder of --path.",
    )
    parser.add_argument(
        "--path", default="", metavar="DIR", help="Parent directory to zip subfolders of (required)"
    )
    add_bool_flag(parser, "--dry-run", help="Print what would be zipped, change nothing")
    add_bool_flag(parser, "--verbose", help="Show per-file progress")
    args = parser.parse_args(argv)

    if not args.path:
        warning("❌ --path is required")
        parser.print_help()
        return 1

    root = scan_root(args.path)

    header_suffix = " 🌵 (dry run)" if args.dry_run else ""
    note("═══════════════════════════════════════════")
    note(f"📦  compress-folders{header_suffix}")
    note("═══════════════════════════════════════════")
    note(f"Parent: {root}")

    compressed = 0
    skipped = 0

    # Matches the shell version's `for dir in "$ROOT_DIR"/*/` glob: dotted
    # directories are skipped (no `dotglob`), and a symlink to a directory IS
    # included, because `*/` matches it.
    folders = sorted(
        path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")
    )

    for folder in folders:
        archive = folder.with_name(folder.name + ".zip")

        if args.dry_run:
            info(f"  🪄 Would zip: {folder.name} → {folder.name}.zip")
            compressed += 1
            continue

        info(f"📦 Compressing '{folder.name}'...")
        try:
            zip_folder(folder, archive, verbose=args.verbose)
        except (OSError, ValueError) as exc:
            # ValueError covers a file whose size changes mid-write and the
            # UnicodeEncodeError raised for surrogate bytes in names off an
            # SMB mount. The shell version isolated each folder in a subshell,
            # so one bad folder never stopped the batch.
            warning(f"  ❌ Failed: {archive} ({exc})")
            skipped += 1
            continue
        success(f"  ✅ {folder.name}.zip")
        compressed += 1

    print()
    note("─────────────────────────────────────────────")
    if args.dry_run:
        success(f"🌵 Would compress: {compressed} folder(s)")
        log("💡 Dry run complete. Nothing was actually changed.")
        return 0

    success(f"✅ Compressed: {compressed}")
    if skipped:
        warning(f"❌ Failed:     {skipped}")
        return 1

    log("🎉 Compression complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
