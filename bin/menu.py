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
from commands import (
    CATEGORIES,
    MENU_KEYS,
    VERSION,
    Category,
    Command,
    Resolved,
    all_commands,
    grouped,
)


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
    counter = f"{shown}/{total}"
    prompt = search_prompt(state)

    right = art.wordmark(colors)
    right += ["", f"  {colors.grey}{counter} commands{colors.reset}", f"  {prompt}"]
    if banner_fits(screen, right) and not state.show_help:
        # The face beside the wordmark, with the count and the search line
        # tucked under the letters.
        screen.lines(art.banner(right, columns=width, colors=colors))
    else:
        # The one-line search bar: the prompt on the left, the count on the right.
        screen.line()
        screen.line(spread(f"  {prompt}", f"{colors.grey}{counter}{colors.reset}  ", width))
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
            left = tui.fit(category_row(row), list_width)
        else:
            left = command_row(
                state,
                row,
                selected=index == state.cursor,
                width=list_width,
                summary=not detail_width,
            )

        detail_index = index - state.offset
        right = detail_lines[detail_index] if detail_index < len(detail_lines) else ""
        screen.line(f"{left}{colors.grey}│{colors.reset} {right}" if detail_width else left)

    draw_footer(screen, state)


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------


def pill(text: str, ground: str) -> str:
    """``text`` on a tinted ground, one cell of padding either side.

    With colour off the ground is empty, so brackets stand in for it: the
    pill keeps its width either way and nothing after it shifts.
    """
    colors = tui.palette()
    if not ground:
        return f"[{text}]"
    return f"{ground} {text} {colors.reset}"


def key_cap(key: str) -> str:
    """A key the way the footer and detail pane name it: `` d ``."""
    colors = tui.palette()
    return f"{colors.key_ground} {key} {colors.reset}" if colors.key_ground else key


def band(text: str, width: int, ground: str) -> str:
    """``text`` fitted to ``width`` columns, all of it on ``ground``.

    Every reset inside ``text`` would end the ground early, so each one is
    followed by the ground again; a pill inside a band keeps its own colour
    and the band resumes after it.
    """
    colors = tui.palette()
    fitted = tui.fit(text, width)
    if not ground:
        return fitted
    return ground + fitted.replace(colors.reset, colors.reset + ground) + colors.reset


def spread(left: str, right: str, width: int) -> str:
    """``left`` and ``right`` on one line, pushed to either edge of ``width``.

    When both do not fit, ``right`` is dropped before ``left`` is cut, since
    the left side carries what the line is about.
    """
    room = width - tui.display_width(left) - tui.display_width(right)
    if room < 1:
        return tui.fit(left, width)
    return left + " " * room + right


def search_prompt(state: Menu) -> str:
    """The search bar: ``che`` between angle quotes, then the query and a caret while typing."""
    colors = tui.palette()
    lead = (
        f"{colors.grey}{LEFT_QUOTE}{colors.reset} "
        f"{colors.bold}{colors.bright_green}che {RIGHT_QUOTE}{colors.reset}"
    )
    if state.searching:
        return f"{lead} {state.query}{colors.bright_green}▏{colors.reset}"
    if state.query:
        return f"{lead} {state.query}"
    return f"{lead} {colors.grey}type to filter{colors.reset}"


def category_row(category: Category) -> str:
    """A category header in the list: ``## Git  Branch hygiene, ...``."""
    colors = tui.palette()
    title = f"{colors.bold}{colors.bright_green}## {category.title}{colors.reset}"
    return f"  {title}  {colors.grey}{category.blurb}{colors.reset}"


def badge(state: Menu, command: Command) -> str:
    """The pill at the end of a command's row: how running it would behave."""
    colors = tui.palette()
    if command.has_dry_twin:
        if state.is_dry(command):
            return pill("DRY", colors.good_pill)
        return pill("LIVE", colors.warn_pill)
    if command.destructive:
        return pill("LIVE", colors.warn_pill)
    if command.macos_only:
        return pill("MACOS", colors.info_pill)
    return ""


def command_row(
    state: Menu, command: Command, *, selected: bool, width: int, summary: bool = False
) -> str:
    """One command's row in the list, exactly ``width`` columns wide.

    Pointer, icon and name on the left, the dry/live pill against the right
    edge, the whole row on a lighter ground while selected. ``summary`` adds
    the command's summary between the two, for when there is no detail pane
    to show it.
    """
    colors = tui.palette()
    pointer = f"{colors.bright_green}{RIGHT_QUOTE}{colors.reset}" if selected else " "
    name = command.name
    if selected:
        name = f"{colors.bold}{colors.bright_green}{name}{colors.reset}"
    left = f"  {pointer} {command.icon} {name}"

    tag = badge(state, command)
    tag_width = tui.display_width(tag) + 1 if tag else 0
    if summary:
        room = width - tui.display_width(left) - tag_width - 3
        if room > 8:
            left += f"  {colors.grey}{tui.truncate(command.summary, room)}{colors.reset}"

    room = width - tag_width
    line = spread(tui.truncate(left, room - 1), f"{tag} " if tag else "", width)
    return band(line, width, colors.selected_ground if selected else "")


# ---------------------------------------------------------------------------
# Detail pane
# ---------------------------------------------------------------------------

# The search bar's angle quotes, spelled as escapes so the linter does not
# take them for a typo of < and >.
LEFT_QUOTE = "\u2039"
RIGHT_QUOTE = "\u203a"

# The detail pane's label column: "command:  ", "dry run:  ".
LABEL_WIDTH = 10


def detail_pane(state: Menu, width: int) -> list[str]:
    """The right-hand column: what the selected command is and what it needs.

    A ``che / Category`` breadcrumb, the name as a ``$`` prompt, the summary,
    then a striped table of what che knows about it.
    """
    colors = tui.palette()
    command = state.selected()
    if command is None:
        return []

    category = next((c.title for c in CATEGORIES if c.key == command.category), "")
    lines: list[str] = [
        f"{colors.grey}che / {category}{colors.reset}",
        f"{colors.grey}${colors.reset} {colors.bold}{colors.bright_green}{command.name}{colors.reset}",
    ]
    lines += wrap(command.summary, width, colors.grey)
    lines.append("")

    for index, (label, values) in enumerate(detail_fields(state, command, width)):
        ground = colors.stripe_ground if index % 2 == 0 else ""
        for line_index, value in enumerate(values):
            title = f"{label}:" if line_index == 0 else ""
            text = f" {colors.grey}{title:<{LABEL_WIDTH}}{colors.reset}{value}"
            lines.append(band(text, width, ground))
    return [tui.truncate(line, width) for line in lines]


def detail_fields(state: Menu, command: Command, width: int) -> list[tuple[str, list[str]]]:
    """The detail table's rows: a label and the lines of its value."""
    colors = tui.palette()
    value_width = max(10, width - LABEL_WIDTH - 2)

    def wrapped(text: str, color: str = "") -> list[str]:
        return [
            f"{color}{line}{colors.reset if color else ''}"
            for line in (textwrap.wrap(text, value_width) or [""])
        ]

    fields: list[tuple[str, list[str]]] = [("command", [f"che {command.name}"])]

    if command.script:
        fields.append(("script", [f"bin/{command.script}"]))
    elif command.builtin:
        fields.append(("script", ["built in to che"]))

    if command.needs:
        found = (
            pill(f"{binary} ✓", colors.good_pill)
            if _which(binary)
            else pill(f"{binary} ✗", colors.bad_pill)
            for binary in command.needs
        )
        fields.append(("needs", [" ".join(found)]))

    if command.has_dry_twin:
        state_pill = (
            pill("on, previews only", colors.good_pill)
            if state.is_dry(command)
            else pill("OFF, changes files", colors.warn_pill)
        )
        fields.append(("dry run", [f"{state_pill} {key_cap('d')}"]))
    elif command.preview:
        fields.append(("dry run", [f"asked on {key_cap('⏎')}"]))
    elif command.destructive:
        fields.append(
            ("warning", wrapped(command.no_preview_reason or "changes files", colors.yellow))
        )

    if command.flags:
        fields.append(("flags", wrapped(" ".join(command.flag_names), colors.grey)))

    if command.setup:
        fields.append(("setup", wrapped(command.setup, colors.yellow)))

    if command.macos_only:
        fields.append(("os", [pill("macOS only", colors.info_pill)]))

    return fields


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


# ---------------------------------------------------------------------------
# Help and footer
# ---------------------------------------------------------------------------


def draw_help(screen: tui.Screen) -> None:
    colors = tui.palette()
    screen.line()
    screen.line(f"  {colors.bold}{colors.bright_green}## Keys{colors.reset}")
    screen.line()
    width = max(len(key) for key, _ in MENU_KEYS) + 3
    for key, description in MENU_KEYS:
        screen.line(
            f"    {colors.bright_green}{key:<{width}}{colors.reset}"
            f"{colors.grey}{description}{colors.reset}"
        )
    screen.line()
    screen.line(f"  {colors.grey}Press any key to go back.{colors.reset}")


def draw_footer(screen: tui.Screen, state: Menu) -> None:
    """The bottom bar: che and its version, the keys or a status, and the actions.

    The two action pills on the right say what ⏎ and d would do to the
    selected command right now: ``run`` or ``preview``, dry run on or off.
    """
    colors = tui.palette()
    screen.pad_to(screen.rows - 2)
    screen.line(f"  {colors.grey}{'─' * max(0, screen.columns - 4)}{colors.reset}")

    brand = f"{colors.bold}{colors.bright_green}[che]{colors.reset} {colors.grey}v{VERSION}{colors.reset}"
    if state.status:
        middle = f"{colors.yellow}{state.status}{colors.reset}"
    else:
        middle = (
            f"{key_cap('j')} {key_cap('k')} {colors.grey}move{colors.reset}  "
            f"{key_cap('/')} {colors.grey}filter{colors.reset}  "
            f"{key_cap('h')} {colors.grey}help{colors.reset}  "
            f"{key_cap('q')} {colors.grey}quit{colors.reset}"
        )
    left = f"  {brand}   {middle}"

    actions = ""
    command = state.selected()
    if command is not None and not state.show_help:
        dry = command.has_dry_twin and state.is_dry(command)
        if command.has_dry_twin:
            toggle = pill(f"dry run: {'on' if dry else 'off'}  d", colors.key_ground)
        else:
            toggle = f"{colors.grey}no dry run{colors.reset}"
        run = pill(f"{'preview' if dry else 'run'} ⏎", colors.run_pill)
        actions = f"{toggle} {run}  "

    screen.line(spread(left, actions, screen.columns))
