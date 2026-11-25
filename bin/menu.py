"""The full-screen menu's model and view: what is listed, how a key moves
through it, and how a frame is drawn.

Running anything is left to ``che.py``, whose menu loop suspends the screen,
launches the selected command and comes back. That keeps the dependency one
way - the dispatcher uses the menu, the menu never calls the dispatcher.

Library module: no shebang, not executable.
"""

from __future__ import annotations

import shutil
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import art
import tui
from commands import MENU_KEYS, VERSION, Category, Command, Resolved, all_commands, grouped


@lru_cache(maxsize=64)
def _which(binary: str) -> str | None:
    """PATH lookup, cached: the menu asks about the same binaries every frame."""
    return shutil.which(binary)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def fuzzy_match(query: str, command: Command) -> int | None:
    """Score ``command`` against ``query`` for the menu's type-to-filter.

    Returns ``None`` when it does not match at all, otherwise a score where
    lower is better: an exact name prefix beats a name substring, which beats a
    match that only landed in the summary or tags, which beats a subsequence
    match ("dbe" -> "delete-by-ext").
    """
    if not query:
        return 0

    needle = query.lower().strip()
    name = command.name.lower()

    if name.startswith(needle):
        return 1
    if needle in name:
        return 2
    words = (command.name, command.summary, command.category, *command.tags)
    if needle in " ".join(words).lower():
        return 3

    # Subsequence: every character of the query appears in order in the name.
    position = 0
    for char in needle:
        found = name.find(char, position)
        if found < 0:
            return None
        position = found + 1
    return 4


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


# What a keypress asks the caller to do; "" is nothing beyond the redraw.
Action = Literal["", "quit", "run", "run-raw", "help"]

# How far PgUp and PgDn move the cursor, in commands.
PAGE = 10


@dataclass
class Menu:
    query: str = ""
    searching: bool = False
    cursor: int = 0
    offset: int = 0
    dry: dict[str, bool] = field(default_factory=dict)
    show_help: bool = False
    status: str = ""

    def __post_init__(self) -> None:
        self.first()

    def matches(self) -> list[Command]:
        scored = [(fuzzy_match(self.query, command), command) for command in all_commands()]
        ranked = sorted(
            ((score, command) for score, command in scored if score is not None),
            key=lambda pair: (pair[0], pair[1].category, pair[1].name),
        )
        return [command for _, command in ranked]

    def rows(self) -> list[Category | Command]:
        """The list as drawn: commands, under their category headers unless searching."""
        commands = self.matches()
        if self.query:
            return list(commands)
        return [row for category, members in grouped(commands) for row in (category, *members)]

    def items(self) -> list[int]:
        """The rows the cursor can land on: the commands, not the headers."""
        return [index for index, row in enumerate(self.rows()) if isinstance(row, Command)]

    def selected(self) -> Command | None:
        rows = self.rows()
        if not rows:
            return None
        self.cursor = max(0, min(self.cursor, len(rows) - 1))
        row = rows[self.cursor]
        return row if isinstance(row, Command) else None

    def resolved(self) -> Resolved | None:
        """The selected command as it would run: its ``-dr`` twin while on preview."""
        command = self.selected()
        return None if command is None else Resolved(command, dry=self.is_dry(command))

    def move(self, delta: int) -> None:
        """One step up or down, wrapping round at either end."""
        items = self.items()
        if not items:
            return
        if self.cursor not in items:
            self.cursor = items[0]
            return
        position = items.index(self.cursor)
        self.cursor = items[(position + delta) % len(items)]

    def jump(self, delta: int) -> None:
        """A page up or down, stopping at either end rather than wrapping."""
        items = self.items()
        if not items:
            return
        position = items.index(self.cursor) if self.cursor in items else 0
        self.cursor = items[max(0, min(len(items) - 1, position + delta))]

    def set_query(self, query: str) -> None:
        self.query = query
        self.first()

    def first(self) -> None:
        items = self.items()
        self.cursor = items[0] if items else 0

    def last(self) -> None:
        items = self.items()
        self.cursor = items[-1] if items else 0

    def is_dry(self, command: Command) -> bool:
        # Anything that can preview previews first: the menu is a browsing UI,
        # and "I pressed Enter to see what it does" should never delete files.
        return self.dry.get(command.name, command.has_dry_twin)

    def toggle_dry(self) -> None:
        """Flip the selected command's preview, or say why it has none to flip."""
        command = self.selected()
        if command is None:
            return
        if command.has_dry_twin:
            self.dry[command.name] = not self.is_dry(command)
            self.status = f"dry-run {'on' if self.is_dry(command) else 'OFF'} for {command.name}"
        elif command.preview:
            self.status = f"{command.name} previews with {command.preview}, asked on ⏎"
        else:
            self.status = f"{command.name} has no preview mode"

    def type(self, key: str) -> None:
        """Add a typed character to the query, dropping into search."""
        self.searching = True
        self.set_query(self.query + key)

    def leave_search(self, *, clear: bool) -> None:
        self.searching = False
        if clear:
            self.set_query("")


# Each key the menu knows, per mode, and what it does to the state. One that
# returns an Action asks the caller to act; None is just a redraw.
KeyHandler = Callable[[Menu], Action | None]

SEARCH_KEYS: dict[str, KeyHandler] = {
    "enter": lambda state: state.leave_search(clear=False),
    "esc": lambda state: state.leave_search(clear=True),
    "backspace": lambda state: state.set_query(state.query[:-1]),
    "ctrl-u": lambda state: state.set_query(""),
    "up": lambda state: state.move(-1),
    "down": lambda state: state.move(1),
    "ctrl-c": lambda _state: "quit",
}

BROWSE_KEYS: dict[str, KeyHandler] = {
    "q": lambda _state: "quit",
    "ctrl-c": lambda _state: "quit",
    "eof": lambda _state: "quit",
    # Esc clears a query left behind by search, and quits once there is none.
    "esc": lambda state: state.set_query("") if state.query else "quit",
    "up": lambda state: state.move(-1),
    "k": lambda state: state.move(-1),
    "down": lambda state: state.move(1),
    "j": lambda state: state.move(1),
    "pgup": lambda state: state.jump(-PAGE),
    "pgdn": lambda state: state.jump(PAGE),
    "home": lambda state: state.first(),
    "g": lambda state: state.first(),
    "end": lambda state: state.last(),
    "G": lambda state: state.last(),
    "/": lambda state: setattr(state, "searching", True),
    "?": lambda state: setattr(state, "show_help", True),
    "d": lambda state: state.toggle_dry(),
    "h": lambda _state: "help",
    "x": lambda _state: "run-raw",
    "enter": lambda _state: "run",
}


def handle_key(state: Menu, key: str) -> Action:
    """Fold one keypress into the menu state. Returns an action for the caller."""
    # A status line lasts until the next key, and any key dismisses the help.
    state.status = ""
    if state.show_help:
        state.show_help = False
        return ""

    handler = (SEARCH_KEYS if state.searching else BROWSE_KEYS).get(key)
    if handler is not None:
        return handler(state) or ""
    # Any other printable key types into the query, and from browsing drops
    # into search, the way a file picker does.
    if len(key) == 1 and key.isprintable():
        state.type(key)
    return ""


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

# The face heads the menu only while the list under it keeps at least this
# many rows. Below that the one-line header takes over, as it always did.
MIN_LIST_ROWS = 8


def banner_fits(screen: tui.Screen, right: list[str]) -> bool:
    """Whether the face and wordmark can head the menu and still leave a list."""
    spare = screen.rows - (art.HEIGHT + 1) - 4
    return spare >= MIN_LIST_ROWS and art.fits(right, screen.columns)


def draw(screen: tui.Screen, state: Menu) -> None:
    colors = tui.palette()
    width = screen.columns

    total = len(all_commands())
    shown = len(state.matches())
    counter = f"{shown}/{total}" if state.query else str(total)
    if state.searching or state.query:
        caret = f"{colors.cyan}▏{colors.reset}" if state.searching else " "
        prompt = f"  {colors.grey}search{colors.reset} {caret}{state.query}"
    else:
        prompt = f"  {colors.grey}type to search   ↑↓ move   ⏎ run   ? keys{colors.reset}"

    right = art.wordmark(colors)
    right += ["", f"  {colors.grey}v{VERSION}  {counter} commands{colors.reset}", prompt]
    if banner_fits(screen, right) and not state.show_help:
        # The face beside the wordmark, with the version, the count and the
        # search line tucked under the letters.
        screen.lines(art.banner(right, columns=width, colors=colors))
    else:
        title = f"{colors.bright_magenta}{colors.bold}che{colors.reset}"
        screen.line()
        screen.line(
            f"  {title} {colors.grey}v{VERSION}{colors.reset}  "
            f"{colors.grey}{counter} commands{colors.reset}"
        )
        screen.line(prompt)
    screen.line(f"  {colors.grey}{'─' * max(0, width - 4)}{colors.reset}")
    header_rows = screen.used

    if state.show_help:
        draw_help(screen)
        return

    body_rows = max(3, screen.rows - header_rows - 4)
    rows = state.rows()
    if not rows:
        screen.line()
        screen.line(f"  {colors.yellow}No command matches {state.query!r}{colors.reset}")
        draw_footer(screen, state)
        return

    # Keep the cursor inside the viewport, with a line of context either side.
    if state.cursor < state.offset + 1:
        state.offset = max(0, state.cursor - 1)
    if state.cursor >= state.offset + body_rows - 1:
        state.offset = min(max(0, len(rows) - body_rows), state.cursor - body_rows + 2)

    detail_width = 0
    if width >= 92:
        detail_width = max(34, width // 2 - 6)
    list_width = width - detail_width - (4 if detail_width else 2)

    detail_lines = detail_pane(state, detail_width) if detail_width else []

    visible = rows[state.offset : state.offset + body_rows]
    for index, row in enumerate(visible, start=state.offset):
        if isinstance(row, Category):
            header = f"{row.title}  {row.blurb}"
            left = tui.fit(f"  {colors.bold}{colors.blue}{header}{colors.reset}", list_width)
        else:
            left = command_row(state, row, selected=index == state.cursor)
            if detail_width:
                left = tui.fit(left, list_width)
            else:
                room = max(0, list_width - tui.display_width(left) - 2)
                left += f"  {colors.grey}{tui.truncate(row.summary, room)}{colors.reset}"

        detail_index = index - state.offset
        right = detail_lines[detail_index] if detail_index < len(detail_lines) else ""
        screen.line(f"{left}{colors.grey}│{colors.reset} {right}" if detail_width else left)

    draw_footer(screen, state)


def command_row(state: Menu, command: Command, *, selected: bool) -> str:
    """One command's entry in the list: pointer, icon, name and its dry/live badge."""
    colors = tui.palette()
    pointer = f"{colors.cyan}▸{colors.reset}" if selected else " "
    name = command.name
    if selected:
        name = f"{colors.bold}{colors.cyan}{name}{colors.reset}"
    elif command.destructive:
        name = f"{colors.yellow}{name}{colors.reset}"

    badge = ""
    if command.has_dry_twin and state.is_dry(command):
        badge = f" {colors.grey}·dry{colors.reset}"
    elif command.destructive:
        badge = f" {colors.red}·live{colors.reset}"
    return f"  {pointer} {command.icon} {name}{badge}"


# The detail pane's label column: "script  ", "needs   ", "warning ".
LABEL_WIDTH = 8


def detail_pane(state: Menu, width: int) -> list[str]:
    """The right-hand column: what the selected command is and what it needs."""
    colors = tui.palette()
    command = state.selected()
    if command is None:
        return []

    lines: list[str] = [f"{colors.bold}{command.name}{colors.reset}", ""]
    lines += wrap(command.summary, width, colors.grey)
    lines.append("")

    def field_line(label: str, value: str) -> str:
        return f"{colors.grey}{label:<{LABEL_WIDTH}}{colors.reset}{value}"

    def field_wrap(label: str, text: str, color: str) -> list[str]:
        return wrap(text, width, color, indent=f"{label:<{LABEL_WIDTH}}")

    if command.script:
        lines.append(field_line("script", f"bin/{command.script}"))
    elif command.builtin:
        lines.append(field_line("script", "built in to che"))

    if command.needs:
        parts = []
        for binary in command.needs:
            found = _which(binary)
            mark = f"{colors.green}✓{colors.reset}" if found else f"{colors.red}✗{colors.reset}"
            parts.append(f"{mark} {binary}")
        lines.append(field_line("needs", "  ".join(parts)))

    if command.flags:
        lines += field_wrap("flags", " ".join(command.flag_names), colors.grey)

    if command.has_dry_twin:
        state_text = (
            f"{colors.green}on{colors.reset} - previews only"
            if state.is_dry(command)
            else f"{colors.red}OFF{colors.reset} - changes files"
        )
        lines.append(field_line("dry-run", f"{state_text}  {colors.grey}(d){colors.reset}"))
    elif command.destructive:
        reason = command.no_preview_reason or "changes files"
        lines += field_wrap("warning", reason, colors.yellow)

    if command.setup:
        lines += field_wrap("setup", command.setup, colors.yellow)

    if command.macos_only:
        lines.append(field_line("os", "macOS only"))

    lines.append("")
    lines.append(f"{colors.grey}⏎ run   x run bare   h help{colors.reset}")
    return [tui.truncate(line, width) for line in lines]


def wrap(text: str, width: int, color: str = "", indent: str = "") -> list[str]:
    colors = tui.palette()
    body = textwrap.wrap(text, max(10, width - len(indent))) or [""]
    out = []
    for index, line in enumerate(body):
        prefix = indent if index == 0 else " " * len(indent)
        out.append(
            f"{colors.grey}{prefix}{colors.reset}{color}{line}{colors.reset if color else ''}"
        )
    return out


def draw_help(screen: tui.Screen) -> None:
    colors = tui.palette()
    screen.line()
    screen.line(f"  {colors.bold}Keys{colors.reset}")
    screen.line()
    width = max(len(key) for key, _ in MENU_KEYS) + 3
    for key, description in MENU_KEYS:
        screen.line(
            f"    {colors.cyan}{key:<{width}}{colors.reset}{colors.grey}{description}{colors.reset}"
        )
    screen.line()
    screen.line(f"  {colors.grey}Press any key to go back.{colors.reset}")


def draw_footer(screen: tui.Screen, state: Menu) -> None:
    colors = tui.palette()
    screen.pad_to(screen.rows - 2)
    screen.line(f"  {colors.grey}{'─' * max(0, screen.columns - 4)}{colors.reset}")
    if state.status:
        screen.line(f"  {colors.yellow}{state.status}{colors.reset}")
    else:
        screen.line(
            f"  {colors.grey}⏎ run   d dry-run   h help   / search   ? keys   q quit{colors.reset}"
        )
