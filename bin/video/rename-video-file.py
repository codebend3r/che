#!/usr/bin/env python3
"""📝 Title-case video filenames (and optionally their folders).

Usage:
  rename-video-file.py [--path=/path/to/dir] [--recursive] [--rename-folders]
                       [--capitalize-preps] [--dry-run] [--ignore-words=W1,W2]

Options:
  --path=DIR             Directory to scan (required)
  --recursive            Recurse into subdirectories (default: true)
  --rename-folders       Rename folders too (default: true)
  --capitalize-preps     Capitalize articles/prepositions (default: false)
  --dry-run              Print renames, change nothing (default: true)
  --ignore-words=LIST    Comma-separated words to leave exactly as written
  --help                 Show help
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    add_bool_flag,
    build_parser,
    info,
    iter_files,
    log,
    note,
    run_cli,
    scan_root,
    warning,
)

__version__ = "3.0.0"

VIDEO_EXTENSIONS = ("mp4", "mkv")

# Every flavour of curly quote, backtick and acute accent people end up with,
# normalised to a plain straight apostrophe.
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "´": "'", "`": "'"})  # noqa: RUF001

# Space out dashes, then pull ALLCAPS-digit codes (ABC-123) back together.
_DASH_SPACING = re.compile(r"\s*-\s*")
_CODE_REJOIN = re.compile(r"\b([A-Z]+)\s*-\s*([0-9]+)")

# Articles, prepositions and conjunctions that stay lowercase mid-title.
_PREPOSITIONS = re.compile(
    r"\b(And|The|A|An|By|For|In|Of|On|To|With|At|But|Or|Nor|So|Yet|As)\b",
    re.IGNORECASE,
)

_FIRST_LETTER = re.compile(r"^([^A-Za-z]*)([A-Za-z])")
_AFTER_DASH = re.compile(r"(-\s*)([^A-Za-z]*)([A-Za-z])")

# "I'm", "You've", "Friend's" - one or two letters after an apostrophe stay low.
_APOSTROPHE_SUFFIX = re.compile(r"'([A-Za-z]{1,2})\b")

# Scene-style video codes such as "abc-1234", uppercased whole.
_CODE = r"\b(?P<code>[a-zA-Z]{3,5}-[0-9]{3,5})\b"
_WORD = r"\b(?P<first>\w)(?P<rest>\w*)"

# Filenames shaped "<prefix> - <title>.<ext>", and the fallback "<title>.<ext>".
_DASHED_NAME = re.compile(r"(.*- )([^.]+)(\..*)", re.DOTALL)
_PLAIN_NAME = re.compile(r"([^.]+)(\..*)", re.DOTALL)


def build_title_pattern(ignore_words: list[str]) -> re.Pattern[str]:
    """The single alternation that does the title-casing.

    Order matters and mirrors the perl original: a video code wins over an
    ignored word, which wins over an ordinary word.

    Ignore-words are regex-escaped, where perl interpolated them raw into the
    alternation. "Leave exactly as written" is what the flag promises, so a
    word containing a dot should match that dot, not any character.
    """
    parts = [_CODE]
    if ignore_words:
        alternation = "|".join(re.escape(word) for word in ignore_words)
        parts.append(rf"\b(?P<keep>{alternation})\b")
    parts.append(_WORD)
    return re.compile("|".join(parts))


def title_case(text: str, pattern: re.Pattern[str]) -> str:
    """Capitalize the first letter of every word, lowercase the rest.

    Video codes are uppercased whole and ignore-words pass through verbatim.

    Note: Python's ``\\w`` and ``\\b`` are Unicode-aware, where the perl
    original ran without ``use utf8`` and so treated a UTF-8 filename as raw
    bytes. Accented titles now title-case correctly instead of being mangled.
    """

    def replace(match: re.Match[str]) -> str:
        if match.group("code"):
            return match.group("code").upper()
        if "keep" in match.groupdict() and match.group("keep"):
            return match.group("keep")
        return match.group("first").upper() + match.group("rest").lower()

    return pattern.sub(replace, text)


def apply_preposition_rules(text: str) -> str:
    """Lowercase mid-title prepositions, then restore the leading capitals."""
    text = _PREPOSITIONS.sub(lambda m: m.group(1).lower(), text)
    # The very first word is capitalized even if it is a preposition, and so is
    # the word after any dash ("Show - the movie" -> "Show - The movie").
    text = _FIRST_LETTER.sub(lambda m: m.group(1) + m.group(2).upper(), text)
    return _AFTER_DASH.sub(lambda m: m.group(1) + m.group(2) + m.group(3).upper(), text)


def normalize(text: str) -> str:
    """Straighten quotes and normalise dash spacing."""
    text = text.translate(_APOSTROPHES)
    text = _DASH_SPACING.sub(" - ", text)
    return _CODE_REJOIN.sub(r"\1-\2", text)


def clean_segment(text: str, pattern: re.Pattern[str], *, capitalize_preps: bool) -> str:
    """Title-case one name segment end to end."""
    result = title_case(text, pattern)
    if not capitalize_preps:
        result = apply_preposition_rules(result)
    return result


def clean_folder_name(name: str, pattern: re.Pattern[str], *, capitalize_preps: bool) -> str:
    """The corrected name for a folder.

    Folders now get the same curly-quote normalisation as files. The shell
    version appeared to do this too, but both of its folder-branch sed patterns
    were the plain ASCII apostrophe - two no-ops - so a folder called
    ``l'auberge`` with a typographic apostrophe was left alone.
    """
    result = clean_segment(normalize(name), pattern, capitalize_preps=capitalize_preps)
    return _APOSTROPHE_SUFFIX.sub(lambda m: "'" + m.group(1).lower(), result)


def clean_file_name(name: str, pattern: re.Pattern[str], *, capitalize_preps: bool) -> str | None:
    """The corrected name for a file, or None when it cannot be parsed.

    Anchored with ``fullmatch`` where the shell version used an unanchored
    ``[[ =~ ]]`` search. The two agree on every ordinary name; the difference
    is dot-leading ones, where the shell version matched from after the dot and
    so renamed ``.hidden movie.mkv`` to ``Hidden Movie.mkv`` - silently
    un-hiding the file. Those are reported as unparseable instead.
    """
    normalized = normalize(name)

    match = _DASHED_NAME.fullmatch(normalized)
    if match:
        prefix, title, ext = match.group(1), match.group(2), match.group(3)
    else:
        match = _PLAIN_NAME.fullmatch(normalized)
        if not match:
            return None
        prefix, title, ext = "", match.group(1), match.group(2)

    prefix = clean_segment(prefix, pattern, capitalize_preps=capitalize_preps)
    title = clean_segment(title, pattern, capitalize_preps=capitalize_preps)

    result = f"{prefix}{title}{ext}"
    return _APOSTROPHE_SUFFIX.sub(lambda m: "'" + m.group(1).lower(), result)


def safe_rename(source: Path, target: Path, *, kind: str) -> bool:
    """Rename ``source`` to ``target`` unless something is already there.

    The shell version used bare ``mv``, which silently clobbers an existing
    file and moves a folder *inside* an existing folder of the same name.
    A case-only change (``abc`` -> ``Abc``) is still allowed, because on a
    case-insensitive filesystem the target "exists" as the source itself.
    """
    try:
        # Inside the try: the source can vanish between the walk and the
        # rename, and samefile() would then raise straight past this function.
        # The shell version's bare `mv` printed an error and carried on.
        if target.exists() and not source.samefile(target):
            warning(f"⚠️ Skipping {kind} (target already exists): {target.name}")
            return False
        source.rename(target)
    except OSError as exc:
        warning(f"⚠️ Could not rename {source.name}: {exc}")
        return False
    return True


def rename_folders(
    root: Path, pattern: re.Pattern[str], *, recursive: bool, capitalize_preps: bool, dry_run: bool
) -> None:
    """Rename folders deepest-first so a parent rename cannot break child paths."""
    directories: list[Path] = []
    for dirpath, _, _ in os.walk(root, topdown=False, followlinks=False):
        directory = Path(dirpath)
        if directory == root:
            continue
        if not recursive and directory.parent != root:
            continue
        directories.append(directory)

    # Sorting the collected list, not os.walk's dirnames: under topdown=False
    # the recursion has already happened, so mutating dirnames does nothing.
    # Deepest first, so renaming a parent cannot invalidate a child's path.
    directories.sort(key=lambda p: (-len(p.parts), p))

    for folder in directories:
        if folder.name.startswith("._"):
            continue

        new_name = clean_folder_name(folder.name, pattern, capitalize_preps=capitalize_preps)
        if new_name == folder.name:
            warning(f"⚠️ Skipping folder (already correct format): {folder.name}")
            continue

        target = folder.with_name(new_name)
        if dry_run:
            log(f"📁 [DRY RUN] Would rename folder: {folder.name} ➡️ {new_name}")
            continue

        if safe_rename(folder, target, kind="folder"):
            log(f"📁 Renaming folder: {folder.name} ➡️ {new_name}")


def rename_files(
    root: Path, pattern: re.Pattern[str], *, recursive: bool, capitalize_preps: bool, dry_run: bool
) -> None:
    """Rename the .mp4/.mkv files themselves."""
    # case_sensitive: this script's find used -name, not -iname, so a file
    # called "Movie.MKV" was never renamed.
    for path in iter_files(
        root, extensions=VIDEO_EXTENSIONS, recursive=recursive, case_sensitive=True
    ):
        new_name = clean_file_name(path.name, pattern, capitalize_preps=capitalize_preps)
        if new_name is None:
            warning(f"Could not parse filename: {path.name}")
            continue

        if new_name == path.name:
            warning(f"⚠️ Skipping (already correct format): {path.name}")
            continue

        target = path.with_name(new_name)
        if dry_run:
            log(f"👓 [DRY RUN] Would rename: {path.name} ➡️ {new_name}")
            continue

        if safe_rename(path, target, kind="file"):
            log(f"📝 Renaming: {path.name} ➡️ {new_name}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="rename-video-file",
        description="📝 Title-case video filenames (and optionally their folders).",
    )
    parser.add_argument("--path", default="", metavar="DIR", help="Directory to scan (required)")
    add_bool_flag(parser, "--recursive", default=True, help="Recurse into subdirectories")
    add_bool_flag(
        parser, "--rename-folders", dest="rename_folders", default=True, help="Rename folders too"
    )
    add_bool_flag(
        parser,
        "--capitalize-preps",
        dest="capitalize_preps",
        help="Capitalize articles and prepositions",
    )
    # Deliberately NOT env_bool: unlike the delete tools, the shell version
    # hard-coded DRY_RUN=true and never read the environment. Honouring it here
    # would let an exported DRY_RUN=false anywhere in the user's shell turn a
    # preview into a mass rename.
    add_bool_flag(
        parser,
        "--dry-run",
        default=True,
        help="Print renames, change nothing",
    )
    parser.add_argument(
        "--ignore-words",
        default="",
        dest="ignore_words",
        metavar="LIST",
        help="Comma-separated words to leave exactly as written",
    )

    info(f"Running command in {Path.cwd()}")
    args = parser.parse_args(argv)

    ignore_words = [word.strip() for word in args.ignore_words.split(",") if word.strip()]

    note(f"Scanning: {args.path}")
    note(f"Recursive: {str(args.recursive).lower()}")
    note(f"Rename Folders: {str(args.rename_folders).lower()}")
    note(f"Capitalize Prepositions: {str(args.capitalize_preps).lower()}")
    note(f"Dry Run: {str(args.dry_run).lower()}")
    if ignore_words:
        note(f"Ignore Words: {','.join(ignore_words)}")
    note("----------------------------------------------------")

    root = scan_root(args.path)
    pattern = build_title_pattern(ignore_words)

    if args.rename_folders:
        rename_folders(
            root,
            pattern,
            recursive=args.recursive,
            capitalize_preps=args.capitalize_preps,
            dry_run=args.dry_run,
        )

    rename_files(
        root,
        pattern,
        recursive=args.recursive,
        capitalize_preps=args.capitalize_preps,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    run_cli(main)
