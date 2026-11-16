#!/usr/bin/env python3
"""🗑️  Delete duplicate MKV/MP4 files under a root directory.

Pipeline:

  1. Parse flags and normalize booleans/strategy (env overrides, then CLI).
  2. Resolve --path to an absolute directory.
  3. Walk every .mkv/.mp4 recursively, skipping AppleDouble "._*" sidecars.
  4. Compute a duplicate group key per file (depends on --strategy).
  5. Bucket files by that key.
  6. For each bucket, keep one member (largest file; ties break lexically by
     path, so the choice is deterministic) and delete the rest.

Usage:
  delete-duplicate-videos.py --path=/path/to/media [--strategy=MODE]
                             [--dry-run] [--verbose]

Strategies (--strategy):

  episode   Same directory + identical SxxEyy token (tv-style names). Files
            without such a token are ignored.
  filename  Same directory + identical basename: exact filename duplicates.
  size      Same directory + identical byte size. Fast, but CAN mis-group
            different videos that coincidentally match size.
  hash      Globally grouped by SHA-256 (byte-identical copies anywhere under
            root). Reads every file fully - slow on huge trees.
  all       Same directory + basename + byte size + SHA-256 must all match.
            Strong confirmation before delete.

Defaults:
  --strategy=episode

Security:
  Defaults to dry-run when invoked by path. The generated
  delete-duplicate-videos wrapper runs it with DRY_RUN=false so interactive use
  deletes; delete-duplicate-videos-dr previews.

Options:
  --path=PATH      Required directory to scan
  --strategy=MODE  episode | filename | size | hash | all
  --dry-run        Show removals only, no deletes (same as env DRY_RUN=true)
  --dry-run=BOOL   Explicit true|false (aliases: yes|no, 1|0)
  --verbose        Extra per-file logging
  --help, -h       This help

Env:
  STRATEGY=MODE       Same spelling as --strategy (default episode)
  DRY_RUN=true|false  Overrides the preview-only default

Examples:
  delete-duplicate-videos.py --path=./Shows --strategy=filename
  DRY_RUN=false delete-duplicate-videos.py --path=./Shows --strategy=hash
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media import LIBRARY_EXTENSIONS
from report import FAIL, OK, PLAN, SAME, WARN, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    build_parser,
    dry_run_complete,
    env_bool,
    format_bytes,
    info,
    iter_files,
    log,
    note,
    note_settings,
    run_cli,
    scan_root,
    warning,
)

__version__ = "3.0.0"


class Dupe(Outcome):
    """Everything a dedupe run can conclude about a file, in summary order."""

    DELETED = (OK, "deleted", "Deleted")
    WOULD_DELETE = (PLAN, "would delete", "Would delete")
    KEPT = (SAME, "", "Kept (largest copy)", Listing.COUNT)
    SKIPPED = (WARN, "skipped", "Skipped")
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


# Called with a file and the reason it is left out of every group.
Skip = Callable[[Path, str], None]

# Glue multiple logical fields into one key without a separator that could
# plausibly appear in a directory name.
KEY_RS = "\x1e"

EPISODE_RE = re.compile(r"[Ss][0-9]{2}[Ee][0-9]{2,3}")

STRATEGY_ALIASES = {
    "episode": "episode",
    "tv": "episode",
    "filename": "filename",
    "file": "filename",
    "basename": "filename",
    "name": "filename",
    "size": "size",
    "bytes": "size",
    "hash": "hash",
    "checksum": "hash",
    "sha256": "hash",
    "digest": "hash",
    "all": "all",
    "combined": "all",
}

# The fields each strategy's group key is joined from, in order. Size comes
# before the digest for `all`, so a file whose size cannot be read is skipped
# before anything spends a full read hashing it.
STRATEGY_FIELDS: dict[str, tuple[str, ...]] = {
    "episode": ("dir", "episode"),
    "filename": ("dir", "name"),
    "size": ("dir", "size"),
    "hash": ("digest",),
    "all": ("dir", "name", "size", "digest"),
}

# 1 MiB chunks: large enough that syscall overhead is irrelevant, small enough
# that a 60 GB remux does not have to fit in memory.
_HASH_CHUNK = 1024 * 1024


def normalize_strategy(value: str) -> str:
    """Collapse the strategy synonyms, or return "" for an unknown value."""
    return STRATEGY_ALIASES.get(value.strip().lower(), "")


def sha256_hex(path: Path) -> str:
    """SHA-256 of a file, streamed.

    The shell version shelled out to openssl / sha256sum / shasum and probed
    which one worked. hashlib is in the standard library, so there is no
    backend to detect and no smoke test to run.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def key_field(path: Path, field: str, *, verbose: bool, skip: Skip) -> str | None:
    """One field of a file's group key, or None when the file must be skipped.

    A file that cannot be read is reported through ``skip`` with the reason.
    """
    match field:
        case "dir":
            return str(path.parent)
        case "name":
            return path.name
        case "episode":
            # None when the name is not TV-shaped: ignored, as in the shell version.
            found = EPISODE_RE.search(path.name)
            return found.group(0) if found else None
        case "size":
            try:
                return str(path.stat().st_size)
            except OSError:
                skip(path, "unreadable size")
                return None
        case "digest":
            if verbose:
                note(f"HASH: {path}")
            try:
                return sha256_hex(path)
            except OSError:
                skip(path, "could not hash")
                return None
        case _:
            raise ValueError(f"unknown key field: {field}")


def group_key(path: Path, strategy: str, *, verbose: bool, skip: Skip) -> str | None:
    """The duplicate-group key for one file, or None to skip it."""
    fields: list[str] = []
    for field in STRATEGY_FIELDS[strategy]:
        value = key_field(path, field, verbose=verbose, skip=skip)
        if value is None:
            return None
        fields.append(value)
    return KEY_RS.join(fields)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="delete-duplicate-videos",
        description="🗑️  Delete duplicate MKV/MP4 files under a root directory.",
        epilog=(
            "Examples:\n"
            "  delete-duplicate-videos.py --path=./Shows --strategy=filename\n"
            "  DRY_RUN=false delete-duplicate-videos.py --path=./Shows --strategy=hash"
        ),
    )
    parser.add_argument("--path", default="", metavar="PATH", help="Directory to scan (required)")
    parser.add_argument(
        "--strategy",
        # `or`, not a get() default: the shell used ${STRATEGY:-episode}, where
        # an exported-but-empty value also falls back.
        default=os.environ.get("STRATEGY") or "episode",
        metavar="MODE",
        help="episode | filename | size | hash | all (default: episode)",
    )
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", True),
        help="Show removals only, no deletes",
    )
    add_bool_flag(parser, "--verbose", help="Extra per-file logging")

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    strategy = normalize_strategy(args.strategy)
    if not strategy:
        warning(f"Invalid --strategy value: {args.strategy}")
        parser.print_help()
        return 1

    note_settings(
        ("Scanning", args.path),
        ("Strategy", strategy),
        ("Dry run", args.dry_run),
        ("Verbose", args.verbose),
    )

    # An empty --path reads "--path is required", where the shell version
    # reported "Missing required argument: --path".
    #
    # Absolute, with ../ collapsed, so group keys built from the parent
    # directory are stable regardless of how --path was spelled. Note this also
    # resolves symlinks mid-path, so a logged path can differ from the one the
    # user typed; grouping and the choice of keeper are unaffected, since every
    # key shares the same root prefix.
    root = scan_root(args.path).resolve()

    if strategy == "size":
        info("NOTICE: grouping by SIZE can flag unrelated videos with identical byte lengths.")
    elif strategy in ("hash", "all"):
        info("NOTICE: hashing reads every scanned file entirely; slow on huge libraries.")

    if args.dry_run:
        info("Running in dry-run mode: no files will be deleted.")
    if args.verbose:
        info("Verbose mode: per-file tracing enabled.")

    started = time.monotonic()
    tally = Tally(Dupe)

    def shown(path: Path) -> str:
        """A file as its line names it: relative to the root, which is printed above."""
        return str(path.relative_to(root))

    def skip(path: Path, reason: str) -> None:
        tally.record(Dupe.SKIPPED, shown(path), reason, item=f"{shown(path)}: {reason}")

    scanned = 0
    groups: dict[str, list[Path]] = {}

    for path in iter_files(root, extensions=LIBRARY_EXTENSIONS):
        scanned += 1
        if args.verbose:
            info(f"SCANNING: {path}")
        key = group_key(path, strategy, verbose=args.verbose, skip=skip)
        if key is not None:
            groups.setdefault(key, []).append(path)

    duplicate_groups = 0
    reclaimed = 0
    keys = sorted(key for key, members in groups.items() if len(members) > 1)

    with tally.progress(len(keys)) as progress:
        for key in keys:
            sized: list[tuple[int, Path]] = []
            for path in groups[key]:
                if not path.is_file():
                    continue  # a symlink to a missing target, or deleted mid-run
                try:
                    sized.append((path.stat().st_size, path))
                except OSError:
                    skip(path, "unreadable size")

            if len(sized) <= 1:
                progress.step(key)
                continue

            # Largest first; same-size ties break alphabetically by path, so the
            # keeper is deterministic across runs and machines.
            sized.sort(key=lambda item: (-item[0], str(item[1])))
            duplicate_groups += 1

            keep_size, keep_path = sized[0]
            progress.step(shown(keep_path))
            tally.record(Dupe.KEPT, shown(keep_path))
            if args.verbose:
                info(f"KEEPING: {keep_path} ({format_bytes(keep_size)})")

            for size, path in sized[1:]:
                detail = f"{format_bytes(size)}; keeps {keep_path.name}"
                if args.dry_run:
                    reclaimed += size
                    tally.record(Dupe.WOULD_DELETE, shown(path), detail)
                    continue
                try:
                    path.unlink()
                except OSError as exc:
                    tally.record(Dupe.FAILED, shown(path), str(exc), item=f"{shown(path)}: {exc}")
                    continue
                reclaimed += size
                tally.record(Dupe.DELETED, shown(path), detail)

    freed = f"~{format_bytes(reclaimed)} {'to free' if args.dry_run else 'freed'}"
    tally.summary(
        "Preview" if args.dry_run else "Summary",
        facts=[
            plural(scanned, "file"),
            plural(duplicate_groups, "duplicate group"),
            freed,
            duration(time.monotonic() - started),
        ],
        notes=[f"Strategy: {strategy}. The largest copy in each group is kept."],
    )
    print()
    if count := tally.count(Dupe.FAILED):
        # Exit status unchanged: a failed delete was only ever a warning.
        warning(f"⚠️  {plural(count, 'file')} could not be deleted.")
    if args.dry_run:
        dry_run_complete("deleted")
    else:
        log("Scanning complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
