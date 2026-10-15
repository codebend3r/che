"""Text surgery on the user's rc files: the managed block and the legacy wrappers.

Every edit is a pure function from text to text - :func:`with_block`,
:func:`without_block`, :func:`without_legacy` - so a caller reads a file once,
chains whatever edits it needs, and writes the result once through
:func:`commit_rc`, which backs the file up first. One write per file is also
one backup per file, so the backup always holds the file as it was before che
touched it.

Library module: no shebang, not executable.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import shellgen
from commands import wrapper_names
from machine import backup_dir
from utils import atomic_write_text

BEGIN = shellgen.BEGIN_MARKER
END = shellgen.END_MARKER


# ---------------------------------------------------------------------------
# Reading and writing
# ---------------------------------------------------------------------------


def read_rc(path: Path) -> str:
    """``path``'s text, or "" when it does not exist yet.

    Bytes that are not UTF-8 (a Latin-1 comment, one stray byte) decode to
    surrogates and :func:`commit_rc` writes them back unchanged. Treating them
    as an unreadable file would hand "" to the next edit, which then writes the
    che block over everything the user had. Any other failure - permissions, a
    directory where the file should be - is raised rather than read as empty.
    """
    try:
        return path.read_text(encoding="utf-8", errors="surrogateescape")
    except FileNotFoundError:
        return ""


def backup_file(path: Path) -> None:
    """Copy ``path`` into the backup directory, under a name no backup has yet."""
    if not path.exists():
        return
    stem = f"{path.name.lstrip('.')}.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    target = backup_dir() / f"{stem}.bak"
    counter = 0
    while target.exists():
        counter += 1
        target = backup_dir() / f"{stem}-{counter}.bak"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)


def commit_rc(path: Path, original: str, updated: str, *, dry_run: bool = False) -> bool:
    """Write ``updated`` over ``path``, which read as ``original``, backing it up first.

    Returns whether that changes anything; a dry run answers without writing.
    """
    if updated == original:
        return False
    if not dry_run:
        backup_file(path)
        atomic_write_text(path, updated)
    return True


# ---------------------------------------------------------------------------
# The managed block
# ---------------------------------------------------------------------------


def find_block(text: str) -> tuple[int, int] | None:
    """Character span of the managed block, or None when it is not there."""
    start = text.find(BEGIN)
    if start < 0:
        return None
    end = text.find(END, start)
    if end < 0:
        # A truncated block (someone deleted the end marker): treat everything
        # from the start marker to end of file as ours rather than appending a
        # second copy that would never be found again.
        return start, len(text)
    return start, end + len(END)


def with_block(text: str, block: str) -> tuple[str, str]:
    """``text`` with the managed block inserted or replaced, and what happened.

    The action is one of ``created``, ``updated``, ``unchanged``. The block goes
    at the *end* of the file on a fresh install so that its definitions win
    over anything defined earlier, and stays exactly where it is on an update
    so a user who moved it keeps their placement.
    """
    span = find_block(text)

    if span is None:
        separator = "" if not text or text.endswith("\n\n") else "\n"
        if text and not text.endswith("\n"):
            separator = "\n\n"
        return f"{text}{separator}{block}", "created"

    start, end = span
    if text[start:end].rstrip() == block.rstrip():
        return text, "unchanged"
    return text[:start] + block.rstrip("\n") + text[end:], "updated"


def without_block(text: str) -> str:
    """``text`` with the managed block taken back out."""
    span = find_block(text)
    if span is None:
        return text
    start, end = span
    return text[:start].rstrip("\n") + "\n" + text[end:].lstrip("\n")


def _managed_lines(text: str) -> range:
    """Line indices the managed block covers, so the legacy scan never enters it."""
    span = find_block(text)
    if span is None:
        return range(0)
    start, end = span
    return range(text.count("\n", 0, start), text.count("\n", 0, end) + 1)


# ---------------------------------------------------------------------------
# Legacy hand-written wrappers
# ---------------------------------------------------------------------------

LEGACY_VARIABLE = "SHELL_FUNCTIONS_BIN"

_ASSIGNMENT = re.compile(rf"^(?:export\s+)?{LEGACY_VARIABLE}=")
_ALIAS = re.compile(r"^alias\s+([A-Za-z0-9_.-]+)=")
# The start of a function definition on a stripped line: `name() {`,
# `function name() {` or `name {`. Group 1 is the name, group 2 the
# parentheses when there are any, group 3 whatever follows the brace.
_FUNCTION_HEAD = re.compile(r"^(?:function\s+)?([A-Za-z0-9_.-]+)\s*(\(\))?\s*\{(.*)")


@dataclass(frozen=True)
class LegacyBlock:
    """One hand-written wrapper (or the helper behind it) found in an rc file."""

    start: int
    end: int
    name: str
    body: str


class Span(NamedTuple):
    """Lines ``start`` up to ``end`` hold one legacy definition, its comment included."""

    start: int
    end: int
    name: str  # the function's name, or "" for the SHELL_FUNCTIONS_BIN assignment


@dataclass(frozen=True)
class LegacyScan:
    """What one pass over an rc file learns about the legacy wrappers in it."""

    lines: list[str]
    managed: range  # line indices of the che block, which is never touched
    spans: list[Span]
    helpers: set[str]

    @property
    def names(self) -> list[str]:
        return [span.name for span in self.spans if span.name]


def find_legacy(text: str) -> list[str]:
    """Names of hand-written wrappers in ``text`` that che now generates.

    Before the installer existed, the documented workflow was to copy the
    repo's ``.zshrc`` wrappers into ``~/.zshrc`` by hand, so most machines have
    a few dozen of them sitting there. They are harmless - the managed block is
    appended after, so its definitions win - but they go stale, which is why
    doctor reports them and ``--replace-legacy`` removes them.
    """
    return _legacy_scan(text).names


def _function_blocks(lines: list[str], managed: range) -> list[LegacyBlock]:
    """Every complete multi-line ``name() { … }`` outside the managed block."""
    blocks: list[LegacyBlock] = []
    index = 0

    while index < len(lines):
        head = None if index in managed else _FUNCTION_HEAD.match(lines[index].strip())
        # Only a `name() {` that ends its line opens a body the brace count
        # below can follow; a one-liner is left alone.
        if not head or not head.group(2) or head.group(3):
            index += 1
            continue

        depth = 1
        cursor = index + 1
        body: list[str] = []
        while cursor < len(lines) and depth > 0:
            depth += lines[cursor].count("{") - lines[cursor].count("}")
            body.append(lines[cursor])
            cursor += 1

        if depth == 0:
            blocks.append(LegacyBlock(index, cursor, head.group(1), "\n".join(body)))
            index = cursor
            continue

        index += 1

    return blocks


def _legacy_scan(text: str) -> LegacyScan:
    """Line spans holding legacy wrappers, plus the helper names among them.

    Seeded with everything that mentions ``SHELL_FUNCTIONS_BIN`` directly, then
    grown: a function that calls a legacy *helper* is legacy too. That second
    step is what handles a table-driven rc file, where the wrappers are built
    by an ``_sf`` helper that itself only calls ``_sf_run``.

    Growth deliberately stops at helpers. A function of the user's own that
    happens to call ``sync-all-branches`` is their automation, not a wrapper,
    and must survive untouched.
    """
    lines = text.splitlines()
    managed = _managed_lines(text)
    blocks = _function_blocks(lines, managed)
    generated = set(wrapper_names())

    marked = {block for block in blocks if LEGACY_VARIABLE in block.body}
    helpers = {block.name for block in marked if block.name not in generated}

    while True:
        grown = {
            block
            for block in blocks
            if block not in marked and any(helper in block.body for helper in helpers)
        }
        if not grown:
            break
        marked |= grown
        helpers |= {block.name for block in grown if block.name not in generated}

    spans = [Span(_extend_upwards(lines, block.start), block.end, block.name) for block in marked]
    spans += [
        Span(_extend_upwards(lines, index), index + 1, "")
        for index, line in enumerate(lines)
        if index not in managed and _ASSIGNMENT.match(line.strip())
    ]
    return LegacyScan(lines, managed, sorted(spans), helpers)


def _extend_upwards(lines: list[str], start: int) -> int:
    """Pull the comment block that documents a wrapper into its span.

    Every wrapper in the old ``.zshrc`` had a banner or a sentence above it.
    Removing the function but leaving its comment behind produces a file full
    of headings with nothing under them, so the span starts at the first line
    of the attached comment instead. The walk stops at the first line that is
    neither a comment nor the single blank line between a banner and what it
    introduces, so a comment belonging to code that stays is never taken.
    """
    cursor = start
    if cursor > 0 and not lines[cursor - 1].strip():
        cursor -= 1
    while cursor > 0 and lines[cursor - 1].lstrip().startswith("#"):
        cursor -= 1
    return cursor if lines[cursor].lstrip().startswith("#") else start


def _consecutive_groups(indices: list[int]) -> list[list[int]]:
    groups: list[list[int]] = []
    for index in sorted(indices):
        if groups and index == groups[-1][-1] + 1:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


def without_legacy(text: str) -> tuple[str, list[str]]:
    """``text`` with its legacy wrappers removed, and the names that went.

    Two passes. The first drops the ``SHELL_FUNCTIONS_BIN`` assignment, every
    function that used it, and the helpers those functions were built from,
    along with the comment documenting each. The second drops the lines that
    *call* a removed helper - which is what makes a table-driven ``~/.zshrc``
    safe to clean: removing an ``_sf`` helper while leaving its forty
    ``_sf <name> …`` lines behind would turn every new shell into forty
    "command not found" errors.

    Calls to removed *wrappers* are never touched, only calls to helpers. A
    line of the user's own that runs ``mount-all-drives`` at login is theirs.
    """
    scan = _legacy_scan(text)
    if not scan.spans:
        return text, []

    lines = scan.lines
    drop: set[int] = set()
    for span in scan.spans:
        drop.update(range(span.start, span.end))

    callers = [
        index
        for index, line in enumerate(lines)
        if index not in drop
        and index not in scan.managed
        and line.strip().split(" ")[0] in scan.helpers
    ]
    for group in _consecutive_groups(callers):
        drop.update(range(_extend_upwards(lines, group[0]), group[-1] + 1))

    # Collapse the runs of blank lines the removal leaves behind, so the rc
    # file does not end up with a hole in it.
    tidied: list[str] = []
    for index, line in enumerate(lines):
        if index in drop or (not line.strip() and tidied and not tidied[-1].strip()):
            continue
        tidied.append(line)

    return "\n".join(tidied).rstrip("\n") + "\n", scan.names


# ---------------------------------------------------------------------------
# Shadowing
# ---------------------------------------------------------------------------

# How a name shadows a wrapper, as find_shadowing reports it.
ALIAS = "alias"
REDEFINED = "redefined after the block"


def find_shadowing(text: str) -> list[tuple[str, str]]:
    """Names in ``text`` that would win over a generated wrapper.

    Two ways that happens, both silent: an alias of the same name (in zsh and
    bash an alias is resolved before a function, so `alias remove-metadata=...`
    makes the wrapper dead code), and a function redefined *after* the managed
    block, since the last definition wins. Definitions before the block are
    fine, so they are not reported.
    """
    names = set(wrapper_names())
    span = find_block(text)
    block_end = span[1] if span else len(text)

    found: list[tuple[str, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        start_of_line, offset = offset, offset + len(line)

        alias = _ALIAS.match(stripped)
        if alias and alias.group(1) in names:
            found.append((alias.group(1), ALIAS))
            continue

        if start_of_line <= block_end:
            # Defined before or inside our block: ours is sourced later and
            # wins, so there is nothing to report.
            continue

        definition = _FUNCTION_HEAD.match(stripped)
        if definition and definition.group(1) in names:
            found.append((definition.group(1), REDEFINED))

    return found
