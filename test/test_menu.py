"""The menu's model: what it lists for a query, how keys move it, and drawing."""

from __future__ import annotations

import menu
import pytest
import tui
from commands import Category, Command, resolve


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("delete-by", 1),  # name prefix
        ("by-ext", 2),  # name substring
        ("extensions", 3),  # summary
        ("dbe", 4),  # subsequence of the name
        ("zzzz", None),
    ],
)
def test_fuzzy_match_scores(query, expected):
    assert menu.fuzzy_match(query, resolve("delete-by-ext").command) == expected


def test_rows_group_commands_under_category_headers():
    rows = menu.Menu().rows()
    assert isinstance(rows[0], Category)
    assert rows[0].title == "Git"
    assert all(isinstance(row, Command) for row in rows[1:3])


def test_a_query_lists_matches_without_headers():
    state = menu.Menu(query="codecs")
    assert [row.name for row in state.rows()][:2] == ["fix-codecs", "show-codecs"]


def test_the_cursor_skips_headers_and_wraps():
    state = menu.Menu()
    items = state.items()
    assert state.cursor == items[0]

    state.move(-1)
    assert state.cursor == items[-1]
    state.move(1)
    assert state.cursor == items[0]
    assert state.selected() is not None


def test_a_page_stops_at_either_end():
    """PgDn near the bottom used to wrap round to the top."""
    state = menu.Menu()
    items = state.items()
    state.last()

    menu.handle_key(state, "pgdn")
    assert state.cursor == items[-1]
    menu.handle_key(state, "pgup")
    assert state.cursor == items[-1 - menu.PAGE]
    state.first()
    menu.handle_key(state, "pgup")
    assert state.cursor == items[0]


def test_typing_searches_and_esc_clears():
    state = menu.Menu()
    for key in "codecs":
        assert menu.handle_key(state, key) == ""
    assert state.searching
    assert state.selected().name == "fix-codecs"

    menu.handle_key(state, "esc")
    assert not state.searching
    assert state.query == ""
    assert state.cursor == state.items()[0]


def test_any_key_dismisses_the_help_without_acting():
    state = menu.Menu()
    menu.handle_key(state, "?")
    assert state.show_help

    assert menu.handle_key(state, "q") == ""
    assert not state.show_help
    assert menu.handle_key(state, "q") == "quit"


def test_d_toggles_the_preview_and_the_status_lasts_until_the_next_key():
    state = menu.Menu(query="delete-by-ext")
    assert state.resolved().name == "delete-by-ext-dr"

    menu.handle_key(state, "d")
    assert state.status == "dry-run OFF for delete-by-ext"
    assert state.resolved().name == "delete-by-ext"

    menu.handle_key(state, "j")
    assert state.status == ""


def test_d_on_a_command_that_previews_by_flag_says_how():
    state = menu.Menu(query="update-local-branches")
    menu.handle_key(state, "d")
    assert state.status == "update-local-branches previews with --dry-run, asked on ⏎"


@pytest.mark.parametrize(("key", "action"), [("enter", "run"), ("x", "run-raw"), ("h", "help")])
def test_run_keys(key, action):
    assert menu.handle_key(menu.Menu(), key) == action


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
@pytest.mark.parametrize("query", ["", "codecs", "zzzz"])
def test_every_drawn_line_fits_the_screen(monkeypatch, size, query):
    monkeypatch.setattr(tui, "size", lambda: size)
    screen = tui.Screen()
    state = menu.Menu(query=query)
    state.status = "a status line"

    menu.draw(screen, state)

    columns, rows = size
    assert 0 < screen.used <= rows
    assert all(tui.display_width(line) <= columns for line in screen._lines)
    assert state.status == "a status line", "drawing must not clear the status"
