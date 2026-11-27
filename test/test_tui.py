"""Terminal primitives: key decoding, width measurement and prompt history."""

from __future__ import annotations

import builtins
import os
from types import SimpleNamespace

import pytest
import tui


@pytest.fixture
def keys(monkeypatch):
    """The writing end of a pipe that ``tui.read_key`` reads as its tty."""
    read_end, write_end = os.pipe()
    monkeypatch.setattr(tui.sys, "stdin", SimpleNamespace(fileno=lambda: read_end))
    with os.fdopen(write_end, "wb", buffering=0) as writer:
        yield writer
    os.close(read_end)


def test_read_key_decodes_multibyte_characters_one_key_at_a_time(keys):
    """The lead byte used to be decoded alone, turning é into U+FFFD and then
    reading the following keystroke along with it."""
    keys.write("é".encode() + b"x" + "🎬".encode() + "日".encode())
    assert [tui.read_key(timeout=1) for _ in range(4)] == ["é", "x", "🎬", "日"]


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (b"\x03", "ctrl-c"),
        (b"\x04", "eof"),
        (b"\r", "enter"),
        (b"\n", "enter"),
        (b"\t", "tab"),
        (b"\x7f", "backspace"),
        (b"\x15", "ctrl-u"),
        (b"\x17", "ctrl-w"),
        (b"\x1b[A", "up"),
        (b"\x1bOB", "down"),
        (b"\x1b[5~", "pgup"),
        (b"\x1b[Z", "shift-tab"),
        (b"\x1b[99~", "unknown"),
        (b"\x1b", "esc"),
        (b"q", "q"),
    ],
)
def test_read_key_names_keys(keys, data, name):
    keys.write(data)
    assert tui.read_key(timeout=1) == name


def test_read_key_times_out_and_reports_eof(keys):
    assert tui.read_key(timeout=0.01) is None
    keys.close()
    assert tui.read_key(timeout=1) == "eof"


@pytest.mark.parametrize(
    ("text", "width"),
    [
        ("abc", 3),
        ("\033[95mabc\033[0m", 3),
        ("日本", 4),
        ("🎬", 2),
        ("🗑️", 2),  # a neutral-width emoji plus U+FE0F
        ("⌨️", 2),  # a narrow symbol promoted by U+FE0F
        ("é", 1),  # a combining accent takes no column
        ("️", 0),
        ("", 0),
    ],
)
def test_display_width(text, width):
    assert tui.display_width(text) == width


def test_truncate_never_splits_an_emoji_from_its_selector():
    """Measured per character, ⌨️ came out one column wide and four of them
    "fit" in five columns, overflowing the row by four."""
    cut = tui.truncate("⌨️⌨️⌨️⌨️", 5)
    assert cut == "⌨️⌨️…"
    assert tui.display_width(cut) <= 5


def test_truncate_and_fit():
    assert tui.truncate("abcdef", 4) == "abc…"
    assert tui.truncate("abc", 4) == "abc"
    assert tui.truncate("abc", 0) == ""
    assert tui.fit("ab", 4) == "ab  "
    assert tui.fit("🎬🎬🎬", 4) == "🎬… "


@pytest.mark.parametrize("icon", ["🎬", "🗂️", "⬇️", "⌨️"])
def test_icon_slot_is_two_columns_whatever_the_icon(icon):
    """The slot is measured, and drawn, as two columns, so a terminal that
    draws an emoji with U+FE0F one column wide no longer shifts its row."""
    slot = tui.icon_slot(icon)
    assert tui.display_width(slot) == 2
    assert tui.display_width(f"  {slot} name") == 9
    assert icon in slot


def test_truncate_keeps_escapes_and_closes_them():
    """A cut row used to lose every colour and its icon with it."""
    text = f"\033[32m{tui.icon_slot('🗂️')} sync-all-repos\033[0m"
    cut = tui.truncate(text, 8)
    assert cut.startswith("\033[32m")
    assert "🗂️" in cut
    assert cut.endswith("…\033[0m")
    assert tui.display_width(cut) == 8


@pytest.mark.parametrize(
    ("reply", "theme"),
    [
        ("\033]11;rgb:ffff/ffff/ffff\033\\", "light"),
        ("\033]11;rgb:1e1e/1e1e/2e2e\a", "dark"),
        ("\033]11;rgba:fa/f8/f0/ff\a", "light"),
        ("garbage", None),
    ],
)
def test_theme_from_reply(reply, theme):
    assert tui.theme_from_reply(reply) == theme


def test_theme_prefers_che_theme_then_colorfgbg(monkeypatch):
    monkeypatch.setattr(tui, "_detected", None)
    monkeypatch.delenv("CHE_THEME", raising=False)
    monkeypatch.delenv("COLORFGBG", raising=False)
    assert tui.theme() == "dark"
    monkeypatch.setenv("COLORFGBG", "0;15")
    assert tui.theme() == "light"
    monkeypatch.setenv("COLORFGBG", "15;default;0")
    assert tui.theme() == "dark"
    monkeypatch.setattr(tui, "_detected", "light")
    assert tui.theme() == "light"
    monkeypatch.setenv("CHE_THEME", "dark")
    assert tui.theme() == "dark"


def test_light_theme_gets_the_light_palette(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(tui, "color_enabled", lambda: True)
    monkeypatch.setenv("CHE_THEME", "light")
    assert tui.palette() is tui.LIGHT
    monkeypatch.setenv("CHE_THEME", "dark")
    assert tui.palette() == tui.Palette()
    # Every role the dark palette tints, the light one tints too.
    assert all(getattr(tui.LIGHT, field) for field in tui.Palette.__dataclass_fields__)


def test_each_prompt_keeps_its_own_history(tmp_path, monkeypatch):
    """`read_history_file` appends to what is already in memory, so asking for
    a path and then a limit offered the path at the limit prompt - and saved it
    into the limit's history file."""
    readline = pytest.importorskip("readline")
    offered: list[list[str]] = []

    def fake_input(_prompt: str) -> str:
        # What the real input() offers on ↑ is whatever history is loaded now.
        length = readline.get_current_history_length()
        offered.append([readline.get_history_item(i) for i in range(1, length + 1)])
        answer = answers.pop(0)
        readline.add_history(answer)
        return answer

    monkeypatch.setattr(builtins, "input", fake_input)
    paths, limits = tmp_path / "history-path", tmp_path / "history-limit"

    answers = ["/one", "5", "/two"]
    assert tui.ask("Path", history_file=paths) == "/one"
    assert tui.ask("Limit", history_file=limits) == "5"
    assert tui.ask("Path", history_file=paths) == "/two"

    assert offered == [[], [], ["/one"]]

    readline.clear_history()
    readline.read_history_file(limits)
    assert readline.get_current_history_length() == 1
    assert readline.get_history_item(1) == "5"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """``tmp_path`` as HOME and cwd, holding ``Movies/``, ``Music/`` and ``notes.txt``."""
    (tmp_path / "Movies").mkdir()
    (tmp_path / "Music").mkdir()
    (tmp_path / "notes.txt").touch()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("M", ["Movies/", "Music/"]),
        ("./Mo", ["./Movies/"]),
        ("~/n", ["~/notes.txt"]),
        ("", ["Movies/", "Music/", "notes.txt"]),
        ("nope/", []),
    ],
)
def test_path_matches_keep_what_was_typed(tree, text, expected):
    assert tui._path_matches(text) == expected


def test_path_matches_take_an_absolute_directory(tree):
    assert tui._path_matches(f"{tree}/Mu") == [f"{tree}/Music/"]


def test_a_completer_works_out_the_matches_once_per_tab():
    """readline asks for match 0, 1, 2, ...; listing the folder on every call
    made a Tab quadratic."""
    calls: list[str] = []

    def match(text: str) -> list[str]:
        calls.append(text)
        return ["a", "b"]

    complete = tui._completer(match)
    assert [complete("x", state) for state in range(3)] == ["a", "b", None]
    assert calls == ["x"]
