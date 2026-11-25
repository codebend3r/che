"""Status output for a script that walks many items, from one to thousands.

Three pieces, each built so the output reads the same at any scale:

* :meth:`Reporter.event` prints one aligned line per item that changed or needs
  attention: a status symbol, a fixed-width verb, the item, then dim detail.
  Items that are already fine print nothing; the summary counts them instead.
* :meth:`Reporter.progress` keeps one transient ``[n/total] item`` line on stderr while
  a terminal is attached, so a long run never looks hung, and erases it before
  any event prints. Piped or redirected, it writes nothing at all.
* :func:`summary` closes the run with a table: one row per outcome with a
  right-aligned count and its items listed one per line beside it, capped so a
  run over thousands of items still fits on a screen, with the overflow counted
  rather than silently dropped.

A script defines everything it can conclude about an item once, as an
:class:`Outcome` enum (live verb plus summary row), and reports through a
:class:`Tally`, whose ``record()`` prints the line and counts the item in one
call so the two can never drift apart.

Symbols are single-column characters rather than emoji, whose width varies
between terminals, so every column lines up. Colour goes through
:func:`tui.palette`, which honours ``NO_COLOR`` and non-tty output; the symbols
and verbs carry the meaning on their own when colour is off.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import Generic, TextIO, TypeVar

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

# A LIST row names at most this many items before collapsing the rest.
LIST_LIMIT = 10


class Listing(Enum):
    """How a summary row shows its items."""

    COUNT = "count"  # the count alone: naming thousands of fine items says nothing
    LIST = "list"  # up to LIST_LIMIT, each cut to the terminal width
    ALL = "all"  # every item, in full: each one needs the reader's attention


@dataclass(frozen=True)
class Row:
    """One outcome in the summary table."""

    tone: Tone
    label: str
    items: Sequence[str]
    listing: Listing = Listing.LIST


def _is_terminal(stream: TextIO) -> bool:
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


class Reporter:
    """The live half of a run's output: event lines and the progress line.

    One per run. It remembers whether anything has been printed yet, so the
    first event opens with a blank line that sets the list apart from the
    script's preamble without leaving a gap when nothing happens at all, and
    which progress line is showing, so an event can erase it first.
    """

    def __init__(self) -> None:
        self.opened = False
        self.active: Progress | None = None

    def event(self, tone: Tone, verb: str, item: str, detail: str = "") -> None:
        """One status line: ``  ✓ updated       feature-x  3 new commits``."""
        if self.active is not None:
            self.active.clear()
        if not self.opened:
            print()
            self.opened = True
        p = tui.palette()
        color = getattr(p, tone.color)
        line = f"  {color}{tone.symbol} {verb:<{VERB_WIDTH}}{p.reset}  {item}"
        if detail:
            line += f"  {p.grey}{detail}{p.reset}"
        print(line, flush=True)

    def progress(self, total: int, *, stream: TextIO | None = None) -> Progress:
        return Progress(self, total, stream=stream or sys.stderr)


class Progress:
    """A single ``[n/total] item`` line, redrawn in place, only on a terminal.

    It writes to stderr so stdout stays a clean record of what happened, and
    its reporter erases it before any event, so the two never share a line.
    Used as a context manager so the line is gone however the loop ends.
    """

    def __init__(self, reporter: Reporter, total: int, *, stream: TextIO) -> None:
        self.reporter = reporter
        self.stream = stream
        self.total = total
        self.done = 0
        self.shown = False
        self.enabled = total > 1 and _is_terminal(stream)

    def __enter__(self) -> Progress:
        self.reporter.active = self
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.clear()
        self.reporter.active = None

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


def _lines(row: Row, width: int | None) -> list[str]:
    """What a row shows beside its count, one entry per terminal line."""
    if row.listing is Listing.COUNT:
        return []
    if row.listing is Listing.ALL:
        return list(row.items)
    visible = row.items[:LIST_LIMIT]
    lines = [tui.truncate(item, width) if width else item for item in visible]
    if hidden := len(row.items) - len(visible):
        p = tui.palette()
        lines.append(f"{p.grey}… and {hidden} more{p.reset}")
    return lines


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
    # Off a terminal nothing is cut: a log or a pipe has no width to fit.
    width = tui.size()[0] - indent if _is_terminal(sys.stdout) else None

    for row in shown:
        color = getattr(p, row.tone.color)
        lead = (
            f"  {color}{row.tone.symbol}{p.reset} {row.label:<{label_width}}"
            f"  {p.bold}{len(row.items):>{count_width}}{p.reset}"
        )
        lines = _lines(row, width)
        print(f"{lead}   {lines[0]}" if lines else lead)
        for line in lines[1:]:
            print(" " * indent + line)

    if notes:
        print()
        for line in notes:
            print(f"  {p.grey}{line}{p.reset}")
    sys.stdout.flush()


class Outcome(Enum):
    """Base for a script's outcome table: subclass it with one member per result.

    Each member is ``(tone, verb, label, listing)``: its live line (no verb
    means the item is counted silently) and its summary row. The summary walks
    the members in declaration order, so declare what changed first, then what
    a dry run would change, what was left alone, and failures last.
    """

    def __init__(self, tone: Tone, verb: str, label: str, listing: Listing = Listing.LIST) -> None:
        self.tone = tone
        self.verb = verb
        self.label = label
        self.listing = listing


@dataclass(frozen=True)
class Entry:
    name: str  # the item, as its live line names it
    item: str  # how the summary row names it, usually the same


# A TypeVar rather than PEP 695 syntax: detect-green-magenta-videos imports
# this under its own OpenCV venv, whose interpreter may predate Python 3.12.
OutcomeT = TypeVar("OutcomeT", bound=Outcome)


class Tally(Generic[OutcomeT]):  # noqa: UP046
    """One run's results, keyed by a script's :class:`Outcome` enum."""

    def __init__(self, outcomes: type[OutcomeT]) -> None:
        self.outcomes = outcomes
        self.report = Reporter()
        self.results: dict[OutcomeT, list[Entry]] = {outcome: [] for outcome in outcomes}

    def record(self, outcome: OutcomeT, name: str, detail: str = "", *, item: str = "") -> None:
        """Count ``name`` under ``outcome`` and print its live line, if it has one."""
        self.results[outcome].append(Entry(name, item or name))
        if outcome.verb:
            self.report.event(outcome.tone, outcome.verb, name, detail)

    def flag(self, outcome: OutcomeT, name: str, reason: str) -> None:
        """Record ``name`` with ``reason`` shown live and kept in the summary listing."""
        self.record(outcome, name, reason, item=f"{name}: {reason}")

    def attempt(
        self,
        action: Callable[[], object],
        name: str,
        *,
        done: OutcomeT,
        failed: OutcomeT,
        detail: str = "",
    ) -> bool:
        """Run ``action`` and record ``name`` as ``done``, or ``failed`` with the OS reason."""
        try:
            action()
        except OSError as exc:
            reason = exc.strerror or str(exc)
            self.flag(failed, name, reason)
            return False
        self.record(done, name, detail)
        return True

    def names(self, outcome: OutcomeT) -> list[str]:
        return [entry.name for entry in self.results[outcome]]

    def count(self, *outcomes: OutcomeT) -> int:
        return sum(len(self.results[outcome]) for outcome in outcomes)

    def progress(self, total: int, *, stream: TextIO | None = None) -> Progress:
        return self.report.progress(total, stream=stream)

    def rows(self) -> Iterator[Row]:
        for outcome in self.outcomes:
            entries = self.results[outcome]
            yield Row(outcome.tone, outcome.label, [e.item for e in entries], outcome.listing)

    def summary(
        self,
        title: str,
        *,
        facts: Sequence[str] = (),
        notes: Sequence[str] = (),
    ) -> None:
        summary(title, list(self.rows()), facts=facts, notes=notes)


def plural(count: int, singular: str, plural_form: str = "") -> str:
    """``1 branch``, ``3 branches``: the count with the right noun."""
    return f"{count} {singular if count == 1 else plural_form or singular + 's'}"
