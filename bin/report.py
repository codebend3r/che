"""Status output for a script that walks many items, from one to thousands.

Three pieces, each built so the output reads the same at any scale:

* :func:`event` prints one aligned line per item that changed or needs
  attention: a status symbol, a fixed-width verb, the item, then dim detail.
  Items that are already fine print nothing; the summary counts them instead.
* :class:`Progress` keeps one transient ``[n/total] item`` line on stderr while
  a terminal is attached, so a long run never looks hung, and erases it before
  any event prints. Piped or redirected, it writes nothing at all.
* :func:`summary` closes the run with a table: one row per outcome with a
  right-aligned count and its items listed one per line beside it, capped so a
  run over thousands of items still fits on a screen, with the overflow counted
  rather than silently dropped.

Symbols are single-column characters rather than emoji, whose width varies
between terminals, so every column lines up. Colour goes through
:func:`tui.palette`, which honours ``NO_COLOR`` and non-tty output; the symbols
and verbs carry the meaning on their own when colour is off.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import TextIO

import tui
from utils import footer_rule


@dataclass(frozen=True)
class Tone:
    symbol: str
    color: str  # a tui.Palette field name


OK = Tone("✓", "green")
ADDED = Tone("+", "green")
NOTE = Tone("•", "cyan")
SAME = Tone("=", "grey")
PLAN = Tone("○", "cyan")
WARN = Tone("!", "yellow")
FAIL = Tone("✗", "red")

# Wide enough for the longest verb in use ("would update", "would delete").
VERB_WIDTH = 12

# Rows list at most this many items before collapsing the rest into a count.
DEFAULT_LIMIT = 10

_active: Progress | None = None
# The first event opens with a blank line, setting the list apart from the
# script's preamble without leaving a gap when nothing happens at all.
_opened = False


def _is_terminal(stream: TextIO) -> bool:
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def event(tone: Tone, verb: str, item: str, detail: str = "") -> None:
    """One status line: ``  ✓ updated      feature-x  3 new from origin/feature-x``."""
    global _opened
    if _active is not None:
        _active.clear()
    if not _opened:
        print()
        _opened = True
    p = tui.palette()
    color = getattr(p, tone.color)
    line = f"  {color}{tone.symbol} {verb:<{VERB_WIDTH}}{p.reset}  {item}"
    if detail:
        line += f"  {p.grey}{detail}{p.reset}"
    print(line, flush=True)


class Progress:
    """A single ``[n/total] item`` line, redrawn in place, only on a terminal.

    It writes to stderr so stdout stays a clean record of what happened, and
    :func:`event` erases it first, so the two never share a line. Used as a
    context manager so the line is gone however the loop ends.
    """

    def __init__(self, total: int, *, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stderr
        self.total = total
        self.done = 0
        self.shown = False
        self.enabled = total > 1 and _is_terminal(self.stream)

    def __enter__(self) -> Progress:
        global _active
        _active = self
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        global _active
        self.clear()
        _active = None

    def step(self, item: str) -> None:
        """Count one more item and show it as the one in progress."""
        self.done += 1
        if not self.enabled:
            return
        p = tui.palette()
        digits = len(str(self.total))
        text = tui.truncate(f"  [{self.done:>{digits}}/{self.total}] {item}", tui.size()[0] - 1)
        self.stream.write(f"\r\033[2K{p.grey}{text}{p.reset}")
        self.stream.flush()
        self.shown = True

    def clear(self) -> None:
        if self.shown:
            self.stream.write("\r\033[2K")
            self.stream.flush()
            self.shown = False


@dataclass(frozen=True)
class Row:
    """One outcome in the summary table.

    ``listed=False`` shows only the count (an "up to date" row over thousands
    of items says nothing useful by naming them). ``limit=None`` lists every
    item, for rows that each need the reader's attention. ``truncate=False``
    lets a long item wrap instead of being cut, for rows whose detail matters.
    """

    tone: Tone
    label: str
    items: Sequence[str]
    listed: bool = True
    limit: int | None = DEFAULT_LIMIT
    truncate: bool = True


def duration(seconds: float) -> str:
    """``0.4s``, ``20s``, ``3m 05s``, ``1h 02m``."""
    if seconds < 10:
        return f"{seconds:.1f}s"
    whole = round(seconds)
    if whole < 60:
        return f"{whole}s"
    minutes, secs = divmod(whole, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def summary(
    title: str, rows: Sequence[Row], *, facts: Sequence[str] = (), notes: Sequence[str] = ()
) -> None:
    """The closing table.

    ``title`` is bold, ``facts`` follow it dimmed (``104 branches · 20s``).
    Empty rows are left out. ``notes`` print dimmed under the table.
    """
    p = tui.palette()
    footer_rule()
    heading = f"{p.bold}{title}{p.reset}"
    if facts:
        heading += f"  {p.grey}{' · '.join(facts)}{p.reset}"
    print(heading)

    shown = [row for row in rows if row.items]
    if shown:
        print()
    label_width = max((tui.display_width(row.label) for row in shown), default=0)
    count_width = max((len(str(len(row.items))) for row in shown), default=0)
    # "  ✓ " + label + "  " + count + "   "
    indent = 4 + label_width + 2 + count_width + 3
    room = tui.size()[0] - indent if sys.stdout.isatty() else 0

    for row in shown:
        color = getattr(p, row.tone.color)
        lead = (
            f"  {color}{row.tone.symbol}{p.reset} {row.label:<{label_width}}"
            f"  {p.bold}{len(row.items):>{count_width}}{p.reset}"
        )
        items = list(row.items) if row.listed else []
        visible = items if row.limit is None else items[: row.limit]
        lines = [tui.truncate(item, room) if room and row.truncate else item for item in visible]
        if hidden := len(items) - len(visible):
            lines.append(f"{p.grey}… and {hidden} more{p.reset}")
        print(f"{lead}   {lines[0]}" if lines else lead)
        for line in lines[1:]:
            print(" " * indent + line)

    if notes:
        print()
        for line in notes:
            print(f"  {p.grey}{line}{p.reset}")
    sys.stdout.flush()
