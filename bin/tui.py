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

import os
import re
import select
import signal
import sys
import termios
import tty
import unicodedata
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from utils import color_enabled

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    """Every escape the UI uses, in one place so NO_COLOR can blank them all."""

    reset: str = "\033[0m"
    bold: str = "\033[1m"
    dim: str = "\033[2m"
    italic: str = "\033[3m"
    underline: str = "\033[4m"
    reverse: str = "\033[7m"

    red: str = "\033[31m"
    green: str = "\033[32m"
    yellow: str = "\033[33m"
    blue: str = "\033[34m"
    magenta: str = "\033[35m"
    cyan: str = "\033[36m"
    white: str = "\033[37m"
    grey: str = "\033[90m"

    bright_magenta: str = "\033[95m"
    bright_cyan: str = "\033[96m"
    bright_green: str = "\033[92m"
    bright_yellow: str = "\033[93m"
    bright_red: str = "\033[91m"

    on_magenta: str = "\033[45m"
    on_grey: str = "\033[100m"


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

_VARIATION_SELECTOR_16 = "️"


def display_width(text: str) -> int:
    """Columns ``text`` occupies, ignoring escape sequences.

    ``len()`` is wrong for the two things that show up in this UI: colour
    escapes (zero width) and emoji (two columns). Getting it wrong misaligns
    every row after it, so the menu measures with this instead.
    """
    chars = list(strip_ansi(text))
    width = 0

    for index, char in enumerate(chars):
        if char == _VARIATION_SELECTOR_16 or unicodedata.combining(char):
            # U+FE0F only asks for the emoji presentation of the character
            # before it; it takes no columns of its own. Counting it as one
            # was worth two columns of drift per row on 🗑️ and friends.
            continue

        if unicodedata.east_asian_width(char) in ("W", "F"):
            width += 2
        elif ord(char) >= 0x1F300:
            # Emoji that Unicode still classifies as neutral (🗑, 🎞) but every
            # terminal draws double width.
            width += 2
        elif index + 1 < len(chars) and chars[index + 1] == _VARIATION_SELECTOR_16:
            # A narrow symbol promoted to emoji presentation (⌨️, ⬆️).
            width += 2
        else:
            width += 1

    return width


def truncate(text: str, width: int, *, ellipsis: str = "…") -> str:
    """Cut ``text`` to ``width`` columns, appending an ellipsis when it had to."""
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text

    budget = width - display_width(ellipsis)
    out: list[str] = []
    used = 0
    for char in strip_ansi(text):
        step = display_width(char)
        if used + step > budget:
            break
        out.append(char)
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
CLEAR = "\033[H\033[2J"


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
    than no TUI at all, so teardown runs from ``__exit__`` *and* from handlers
    for SIGINT/SIGTERM/SIGHUP, and is written to be safe to call twice.
    """

    def __init__(self, *, alt_screen: bool = True) -> None:
        self.alt_screen = alt_screen
        self.fd = -1
        self._saved: list | None = None
        self._active = False
        self._previous_handlers: dict[int, object] = {}
        self.resized = False

    # -- lifecycle ------------------------------------------------------
    def __enter__(self) -> Term:
        self.fd = sys.stdin.fileno()
        with suppress(termios.error, ValueError):
            self._saved = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)

        if self.alt_screen:
            self._write(ALT_SCREEN_ON + CURSOR_HIDE)

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

        if self.alt_screen:
            self._write(CURSOR_SHOW + ALT_SCREEN_OFF)
        if self._saved is not None:
            with suppress(termios.error, ValueError):
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)

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
        def on_resize(_signum: int, _frame: object) -> None:
            self.resized = True

        def on_kill(signum: int, _frame: object) -> None:
            self.close()
            # Re-raise with the default disposition so the exit status is the
            # 128+N a shell expects, rather than a plain 0.
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

        for signum, handler in ((signal.SIGWINCH, on_resize),):
            with suppress(ValueError, OSError):
                self._previous_handlers[signum] = signal.signal(signum, handler)

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


def read_key(timeout: float | None = None) -> str | None:
    """Read one keypress in raw mode and return a name for it.

    Returns ``None`` on timeout (used so a SIGWINCH can redraw a frame that is
    otherwise blocked in ``read``). Unknown escape sequences are swallowed
    rather than leaking their bytes into a filter box.
    """
    fd = sys.stdin.fileno()

    if timeout is not None:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None

    try:
        first = os.read(fd, 1).decode("utf-8", "replace")
    except (OSError, InterruptedError):
        return None
    if not first:
        return "eof"

    if first == "\x03":
        return "ctrl-c"
    if first == "\x04":
        return "eof"
    if first in ("\r", "\n"):
        return "enter"
    if first == "\t":
        return "tab"
    if first in ("\x7f", "\b"):
        return "backspace"
    if first == "\x15":
        return "ctrl-u"
    if first == "\x17":
        return "ctrl-w"
    if first != "\033":
        # A multi-byte UTF-8 character arrives one byte at a time.
        if ord(first[0]) >= 0x80:
            extra = b""
            for _ in range(3):
                ready, _, _ = select.select([fd], [], [], 0.01)
                if not ready:
                    break
                extra += os.read(fd, 1)
            return (first.encode("utf-8", "surrogateescape") + extra).decode("utf-8", "replace")
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
        self.columns, self.rows = size()
        self._lines: list[str] = []

    def start(self) -> None:
        self.columns, self.rows = size()
        self._lines = []

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


def _setup_readline(history_file: Path | None = None) -> object | None:
    """Enable editing, filename completion and history for ``input()``.

    macOS ships readline as libedit, which needs a different bind syntax; both
    are handled. A missing readline module is not fatal - the prompt just loses
    arrow-key editing.
    """
    try:
        import readline
    except ImportError:
        return None

    if "libedit" in (getattr(readline, "__doc__", "") or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")

    readline.set_completer_delims(" \t\n=")

    if history_file is not None:
        with suppress(OSError):
            history_file.parent.mkdir(parents=True, exist_ok=True)
            if history_file.exists():
                readline.read_history_file(history_file)
        readline.set_history_length(200)

    return readline


def ask(
    label: str,
    *,
    default: str = "",
    kind: str = "text",
    choices: Sequence[str] = (),
    history_file: Path | None = None,
) -> str:
    """Ask one question and return the answer, or the default on empty input.

    ``kind="path"`` turns on filename completion; ``kind="choice"`` shows the
    valid values and re-asks until one of them is given.
    """
    colors = palette()
    readline = _setup_readline(history_file)

    if readline is not None:
        if kind == "path":
            readline.set_completer(_path_completer)
        elif choices:
            readline.set_completer(_choice_completer(choices))
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
    multi: bool = True,
) -> list[int]:
    """A checkbox / radio list, driven with the arrow keys.

    Returns the indices the user accepted. Falls back to a numbered text
    prompt when there is no tty, so the wizard still works over a pipe.
    """
    chosen = set(selected)

    if not is_interactive():
        return sorted(chosen)

    colors = palette()
    cursor = min(chosen, default=0)

    with Term() as term:
        screen = Screen()
        while True:
            screen.start()
            screen.line()
            screen.line(f"  {colors.bold}{title}{colors.reset}")
            screen.line()
            for index, (label, hint) in enumerate(options):
                mark = "◉" if index in chosen else "○"
                if not multi:
                    mark = "●" if index in chosen else "○"
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
                if multi:
                    chosen.symmetric_difference_update({cursor})
                else:
                    chosen = {cursor}
            elif key == "a" and multi:
                chosen = set(range(len(options))) if len(chosen) < len(options) else set()
            elif key == "enter":
                if not chosen and not multi:
                    chosen = {cursor}
                term.close()
                return sorted(chosen)
            elif key in ("q", "esc", "ctrl-c"):
                term.close()
                return []


def _path_completer(text: str, state: int) -> str | None:
    """readline completer offering filesystem paths, with a / on directories."""
    expanded = Path(os.path.expandvars(text)).expanduser()
    typed_directory = (
        str(expanded.parent) if str(expanded.parent) != "." or text.startswith(".") else ""
    )
    directory = expanded.parent if str(expanded.parent) else Path()
    stem = expanded.name if not text.endswith("/") else ""
    if text.endswith("/"):
        directory = expanded

    try:
        entries = sorted(entry.name for entry in directory.iterdir())
    except OSError:
        return None

    matches = []
    for entry in entries:
        if not entry.startswith(stem):
            continue
        full = str(directory / entry) if typed_directory or text.endswith("/") else entry
        matches.append(f"{full}/" if (directory / entry).is_dir() else full)

    return matches[state] if state < len(matches) else None


def _choice_completer(choices: Sequence[str]):
    def complete(text: str, state: int) -> str | None:
        matches = [choice for choice in choices if choice.startswith(text)]
        return matches[state] if state < len(matches) else None

    return complete


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
