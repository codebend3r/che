"""Terminal primitives for the interactive parts of ``che``.

Standard library only, like everything else here: no curses windows, no
third-party TUI toolkit. What that buys is a menu that runs from a bare
``python3`` on a freshly cloned machine, which is the whole point of this repo.

What this module provides:

* :class:`Term` - alternate screen, hidden cursor and raw input, restored on
  every exit path including SIGINT, SIGTERM and an uncaught exception.
* :func:`read_key` - one keypress, decoded into a name (``"up"``, ``"enter"``,
  ``"ctrl-c"``) rather than a raw escape sequence.
* :class:`Screen` - a frame buffer. Frames are composed in memory and written
  with a single ``write()``, which is what keeps the menu from flickering.
* :func:`display_width` and :func:`fit` - width-aware truncation and padding,
  so a row with an emoji in it still lines up.
* :func:`ask`, :func:`confirm`, :func:`choose` - line-based prompts with
  readline editing, filename completion and per-prompt history.

Library module: no shebang, not executable.
"""

from __future__ import annotations

import functools
import os
import re
import select
import signal
import sys
import termios
import tty
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, TracebackType

from utils import color_enabled

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    """Every escape the UI uses, in one place so NO_COLOR can blank them all."""

    reset: str = "\033[0m"
    bold: str = "\033[1m"

    red: str = "\033[31m"
    green: str = "\033[32m"
    yellow: str = "\033[33m"
    blue: str = "\033[34m"
    cyan: str = "\033[36m"
    grey: str = "\033[90m"
    bright_magenta: str = "\033[95m"


PLAIN = Palette(**{field: "" for field in Palette.__dataclass_fields__})


def palette() -> Palette:
    """Colors when the terminal wants them, empty strings when it does not."""
    return Palette() if color_enabled() else PLAIN


_ANSI = re.compile(r"\033\[[0-9;]*[A-Za-z]|\033\][^\a]*(?:\a|\033\\)")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


# ---------------------------------------------------------------------------
# Width
# ---------------------------------------------------------------------------

_VARIATION_SELECTOR_16 = "\ufe0f"


def _is_modifier(char: str) -> bool:
    """Takes no columns of its own: U+FE0F or a combining mark.

    U+FE0F only asks for the emoji presentation of the character before it.
    Counting it as one column was worth two columns of drift per row on 🗑️.
    """
    return char == _VARIATION_SELECTOR_16 or bool(unicodedata.combining(char))


def _clusters(text: str) -> Iterator[tuple[str, int]]:
    """``text`` without escapes, as (character plus its modifiers, columns) pairs.

    ``display_width`` and ``truncate`` both measure through this, so a cut can
    never land between an emoji and the selector that makes it two columns.
    """
    chars = strip_ansi(text)
    index = 0
    while index < len(chars):
        end = index + 1
        while end < len(chars) and _is_modifier(chars[end]):
            end += 1
        cluster = chars[index:end]
        base = cluster[0]

        if _is_modifier(base):
            # A modifier with nothing before it to modify.
            width = 0
        elif unicodedata.east_asian_width(base) in ("W", "F"):
            width = 2
        elif ord(base) >= 0x1F300:
            # Emoji that Unicode still classifies as neutral (🗑, 🎞) but every
            # terminal draws double width.
            width = 2
        elif cluster[1:2] == _VARIATION_SELECTOR_16:
            # A narrow symbol promoted to emoji presentation (⌨️, ⬆️).
            width = 2
        else:
            width = 1

        yield cluster, width
        index = end


def display_width(text: str) -> int:
    """Columns ``text`` occupies, ignoring escape sequences.

    ``len()`` is wrong for the two things that show up in this UI: colour
    escapes (zero width) and emoji (two columns). Getting it wrong misaligns
    every row after it, so the menu measures with this instead.
    """
    return sum(width for _, width in _clusters(text))


def truncate(text: str, width: int, *, ellipsis: str = "…") -> str:
    """Cut ``text`` to ``width`` columns, appending an ellipsis when it had to."""
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text

    budget = width - display_width(ellipsis)
    out: list[str] = []
    used = 0
    for cluster, step in _clusters(text):
        if used + step > budget:
            break
        out.append(cluster)
        used += step
    return "".join(out) + ellipsis


def fit(text: str, width: int) -> str:
    """Truncate to ``width`` columns, then pad with spaces to exactly that."""
    cut = truncate(text, width)
    return cut + " " * max(0, width - display_width(cut))


def hyperlink(label: str, url: str) -> str:
    """An OSC 8 terminal hyperlink, or the bare label when colour is off."""
    if not color_enabled():
        return label
    return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"


# ---------------------------------------------------------------------------
# Terminal control
# ---------------------------------------------------------------------------

ALT_SCREEN_ON = "\033[?1049h"
ALT_SCREEN_OFF = "\033[?1049l"
CURSOR_HIDE = "\033[?25l"
CURSOR_SHOW = "\033[?25h"


def size() -> tuple[int, int]:
    """Terminal size as ``(columns, rows)``, with sane fallbacks."""
    try:
        columns, rows = os.get_terminal_size(sys.__stdout__.fileno())
    except (OSError, ValueError, AttributeError):
        columns, rows = 80, 24
    return max(40, columns), max(10, rows)


def is_interactive() -> bool:
    """Whether a full-screen UI is possible at all."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (ValueError, AttributeError):
        return False


class Term:
    """Alternate screen + raw input, restored no matter how the block exits.

    A TUI that leaves the terminal in raw mode with the cursor hidden is worse
    than no TUI at all, so teardown runs from ``__exit__`` (which an exception,
    Ctrl-C's KeyboardInterrupt included, also reaches) *and* from handlers for
    SIGTERM/SIGHUP, and is written to be safe to call twice.
    """

    def __init__(self, *, alt_screen: bool = True) -> None:
        self.alt_screen = alt_screen
        self.fd = -1
        self._saved: list | None = None
        self._active = False
        self._previous_handlers: dict[int, object] = {}

    # -- lifecycle ------------------------------------------------------
    def __enter__(self) -> Term:
        self.fd = sys.stdin.fileno()
        with suppress(termios.error, ValueError):
            self._saved = termios.tcgetattr(self.fd)
        self.resume()

        self._active = True
        self._install_handlers()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._active:
            return
        self._active = False
        self.suspend()
        self._restore_handlers()

    # -- suspending, for running a child command in the normal screen ----
    def suspend(self) -> None:
        """Drop back to the normal screen and cooked input."""
        if self.alt_screen:
            self._write(CURSOR_SHOW + ALT_SCREEN_OFF)
        if self._saved is not None:
            with suppress(termios.error, ValueError):
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)

    def resume(self) -> None:
        """Return to the full-screen UI after :meth:`suspend`."""
        with suppress(termios.error, ValueError):
            tty.setraw(self.fd)
        if self.alt_screen:
            self._write(ALT_SCREEN_ON + CURSOR_HIDE)

    # -- signals --------------------------------------------------------
    def _install_handlers(self) -> None:
        def on_kill(signum: int, _frame: object) -> None:
            self.close()
            # Re-raise with the default disposition so the exit status is the
            # 128+N a shell expects, rather than a plain 0.
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

        for signum in (signal.SIGTERM, signal.SIGHUP):
            with suppress(ValueError, OSError):
                self._previous_handlers[signum] = signal.signal(signum, on_kill)

    def _restore_handlers(self) -> None:
        for signum, handler in self._previous_handlers.items():
            with suppress(ValueError, OSError, TypeError):
                signal.signal(signum, handler)  # type: ignore[arg-type]
        self._previous_handlers.clear()

    # -- output ---------------------------------------------------------
    @staticmethod
    def _write(text: str) -> None:
        with suppress(OSError, ValueError):
            sys.stdout.write(text)
            sys.stdout.flush()


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

_CONTROL_KEYS = {
    "\x03": "ctrl-c",
    "\x04": "eof",
    "\r": "enter",
    "\n": "enter",
    "\t": "tab",
    "\x7f": "backspace",
    "\b": "backspace",
    "\x15": "ctrl-u",
    "\x17": "ctrl-w",
}
_CSI_KEYS = {
    "A": "up",
    "B": "down",
    "C": "right",
    "D": "left",
    "H": "home",
    "F": "end",
    "Z": "shift-tab",
}
_CSI_TILDE_KEYS = {
    "1": "home",
    "3": "delete",
    "4": "end",
    "5": "pgup",
    "6": "pgdn",
    "7": "home",
    "8": "end",
}


def _utf8_tail(lead: int) -> int:
    """How many continuation bytes follow ``lead`` in a UTF-8 sequence."""
    if 0xC0 <= lead < 0xE0:
        return 1
    if 0xE0 <= lead < 0xF0:
        return 2
    if 0xF0 <= lead < 0xF8:
        return 3
    return 0


def read_key(timeout: float | None = None) -> str | None:
    """Read one keypress in raw mode and return a name for it.

    Returns ``None`` on timeout, which lets the menu redraw for a resize while
    no key is pressed. Unknown escape sequences are swallowed rather than
    leaking their bytes into a filter box.
    """
    fd = sys.stdin.fileno()

    if timeout is not None:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None

    try:
        raw = os.read(fd, 1)
    except OSError:
        return None
    if not raw:
        return "eof"

    # A multi-byte UTF-8 character arrives one byte at a time. Its lead byte
    # says exactly how many more belong to it, so the next keystroke is never
    # read along with it.
    for _ in range(_utf8_tail(raw[0])):
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            break
        raw += os.read(fd, 1)
    first = raw.decode("utf-8", "replace")

    if first in _CONTROL_KEYS:
        return _CONTROL_KEYS[first]
    if first != "\033":
        return first

    # Escape, possibly introducing a sequence. A lone Escape has nothing
    # following it, which is what the short select() below distinguishes.
    ready, _, _ = select.select([fd], [], [], 0.05)
    if not ready:
        return "esc"

    second = os.read(fd, 1).decode("utf-8", "replace")
    if second not in ("[", "O"):
        return "esc"

    params = ""
    while True:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            return "esc"
        char = os.read(fd, 1).decode("utf-8", "replace")
        if char.isdigit() or char == ";":
            params += char
            continue
        if char == "~":
            return _CSI_TILDE_KEYS.get(params, "unknown")
        return _CSI_KEYS.get(char, "unknown")


# ---------------------------------------------------------------------------
# Frame buffer
# ---------------------------------------------------------------------------


class Screen:
    """Compose a frame in memory, then paint it in one write."""

    def __init__(self) -> None:
        self.start()

    def start(self) -> None:
        self.columns, self.rows = size()
        self._lines: list[str] = []

    def line(self, text: str = "") -> None:
        self._lines.append(truncate(text, self.columns))

    def lines(self, texts: Iterable[str]) -> None:
        for text in texts:
            self.line(text)

    @property
    def used(self) -> int:
        return len(self._lines)

    def pad_to(self, row: int) -> None:
        while len(self._lines) < row:
            self._lines.append("")

    def flush(self) -> None:
        # \033[K after each line clears whatever the previous frame left there,
        # which is cheaper and steadier than clearing the whole screen first.
        body = "\033[K\r\n".join(self._lines[: self.rows])
        with suppress(OSError, ValueError):
            sys.stdout.write("\033[H" + body + "\033[K\033[J")
            sys.stdout.flush()


# ---------------------------------------------------------------------------
# Line prompts (used outside the alternate screen)
# ---------------------------------------------------------------------------


@functools.cache
def _readline() -> ModuleType | None:
    """The readline module, set up once for editing and filename completion.

    macOS ships readline as libedit, which needs a different bind syntax; both
    are handled. A missing readline module is not fatal - the prompt just loses
    arrow-key editing.
    """
    try:
        import readline
    except ImportError:
        return None

    if "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")

    readline.set_completer_delims(" \t\n=")
    return readline


def _load_history(readline: ModuleType, history_file: Path | None) -> None:
    """Make ``history_file`` the only history the next ``input()`` offers.

    ``read_history_file`` appends to what is already in memory, so without the
    clear every prompt would offer every earlier prompt's answers - and save
    them all into its own file.
    """
    readline.clear_history()
    if history_file is None:
        return
    with suppress(OSError):
        history_file.parent.mkdir(parents=True, exist_ok=True)
        if history_file.exists():
            readline.read_history_file(history_file)
    readline.set_history_length(200)


def ask(
    label: str,
    *,
    default: str = "",
    kind: str = "text",
    choices: Sequence[str] = (),
    history_file: Path | None = None,
) -> str:
    """Ask one question and return the answer, or the default on empty input.

    ``kind="path"`` turns on filename completion; ``choices`` shows the valid
    values and re-asks until one of them is given.
    """
    colors = palette()
    readline = _readline()

    if readline is not None:
        _load_history(readline, history_file)
        if kind == "path":
            readline.set_completer(_completer(_path_matches))
        elif choices:
            readline.set_completer(
                _completer(lambda text: [c for c in choices if c.startswith(text)])
            )
        else:
            readline.set_completer(lambda *_: None)

    suffix = ""
    if choices:
        suffix = f" {colors.grey}[{'/'.join(choices)}]{colors.reset}"
    elif default:
        suffix = f" {colors.grey}[{default}]{colors.reset}"

    prompt = f"{colors.cyan}?{colors.reset} {colors.bold}{label}{colors.reset}{suffix}: "

    while True:
        try:
            answer = input(prompt).strip()
        except EOFError:
            print()
            return default

        if not answer:
            answer = default
        if kind == "path" and answer:
            answer = str(Path(os.path.expandvars(answer)).expanduser())
        if choices and answer not in choices:
            print(f"{colors.yellow}  Pick one of: {', '.join(choices)}{colors.reset}")
            continue

        if readline is not None and history_file is not None and answer:
            with suppress(OSError):
                readline.write_history_file(history_file)
        return answer


def confirm(question: str, *, default: bool = True) -> bool:
    """A yes/no prompt. Anything unparseable re-asks rather than guessing."""
    colors = palette()
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            answer = (
                input(
                    f"{colors.cyan}?{colors.reset} {colors.bold}{question}{colors.reset} "
                    f"{colors.grey}[{hint}]{colors.reset} "
                )
                .strip()
                .lower()
            )
        except EOFError:
            print()
            return default
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def choose(
    title: str,
    options: Sequence[tuple[str, str]],
    *,
    selected: Iterable[int] = (),
) -> list[int]:
    """A checkbox list, driven with the arrow keys.

    Returns the indices the user accepted. With no tty there is nothing to
    drive, so the preselection comes back unchanged and the wizard still works
    over a pipe.
    """
    chosen = set(selected)

    if not is_interactive():
        return sorted(chosen)

    colors = palette()
    cursor = min(chosen, default=0)

    with Term():
        screen = Screen()
        while True:
            screen.start()
            screen.line()
            screen.line(f"  {colors.bold}{title}{colors.reset}")
            screen.line()
            for index, (label, hint) in enumerate(options):
                mark = "◉" if index in chosen else "○"
                pointer = f"{colors.cyan}▸{colors.reset}" if index == cursor else " "
                body = f"{mark} {label}"
                if index == cursor:
                    body = f"{colors.bold}{body}{colors.reset}"
                detail = f"  {colors.grey}{hint}{colors.reset}" if hint else ""
                screen.line(f"  {pointer} {body}{detail}")
            screen.line()
            screen.line(
                f"  {colors.grey}↑↓ move   space toggle   enter accept   q cancel{colors.reset}"
            )
            screen.flush()

            key = read_key(timeout=0.5)
            if key is None:
                continue
            if key in ("up", "k"):
                cursor = (cursor - 1) % len(options)
            elif key in ("down", "j"):
                cursor = (cursor + 1) % len(options)
            elif key == " ":
                chosen.symmetric_difference_update({cursor})
            elif key == "a":
                chosen = set(range(len(options))) if len(chosen) < len(options) else set()
            elif key == "enter":
                return sorted(chosen)
            elif key in ("q", "esc", "ctrl-c"):
                return []


def _completer(match: Callable[[str], list[str]]) -> Callable[[str, int], str | None]:
    """A readline completer over ``match(text)``, worked out once per Tab.

    readline asks for match 0, 1, 2, ... until it gets None. Listing the
    matches afresh on every call made one Tab in a folder of a few thousand
    entries on an SMB share quadratic in stats, which reads as a hang.
    """
    matches: list[str] = []

    def complete(text: str, state: int) -> str | None:
        nonlocal matches
        if state == 0:
            matches = match(text)
        return matches[state] if state < len(matches) else None

    return complete


def _path_matches(text: str) -> list[str]:
    """Paths completing ``text`` as typed, ``~`` and all, with a / on directories."""
    head, sep, stem = text.rpartition("/")
    directory = Path(os.path.expandvars(head + sep or ".")).expanduser()
    try:
        with os.scandir(directory) as entries:
            found = sorted(
                (entry for entry in entries if entry.name.startswith(stem)),
                key=lambda entry: entry.name,
            )
            return [f"{head}{sep}{entry.name}{'/' if entry.is_dir() else ''}" for entry in found]
    except OSError:
        return []


def pause(message: str = "Press any key to continue") -> None:
    """Wait for a keypress, in raw mode so any key works (not just Enter)."""
    colors = palette()
    sys.stdout.write(f"\n{colors.grey}{message}…{colors.reset}")
    sys.stdout.flush()
    if is_interactive():
        with Term(alt_screen=False):
            read_key()
    sys.stdout.write("\n")
    sys.stdout.flush()
