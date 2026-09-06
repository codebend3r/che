"""The banner: the face beside the wordmark, and the wordmark alone when it cannot fit."""

from __future__ import annotations

import art
import tui

PLAIN = tui.PLAIN


def test_face_and_wordmark_have_the_shape_the_screens_assume():
    face = art.face_lines()
    assert len(face) == art.HEIGHT == 18
    assert max(len(line) for line in face) <= 32
    assert all(line == line.rstrip() for line in face), "trailing spaces misalign the column"
    assert len(art.logo_lines()) == 6


def test_compose_centres_the_shorter_block_on_the_taller():
    assert art.compose(["a"] * 5, ["b"], gap=1) == ["a", "a", "a b", "a", "a"]


def test_compose_pads_by_display_width_not_len():
    left = ["\033[95mab\033[0m", "abcd"]
    rows = art.compose(left, ["x", "y"], gap=1)
    assert [tui.strip_ansi(row) for row in rows] == ["ab   x", "abcd y"]


def test_banner_puts_the_wordmark_beside_the_face_when_there_is_room():
    right = [*art.wordmark(PLAIN), "  subtitle"]
    rows = art.banner(right, columns=80, colors=PLAIN)
    assert len(rows) == art.HEIGHT
    assert max(len(row) for row in rows) <= 80
    assert any("██████╗" in row for row in rows)
    assert any(row.endswith("subtitle") for row in rows)
    assert "██████╗" not in rows[0], "the wordmark sits in the middle of the face"


def test_banner_paints_the_face_in_the_wordmark_colour():
    colors = tui.Palette()
    rows = art.banner(art.wordmark(colors), columns=80, colors=colors)
    assert all(row.startswith(colors.bright_magenta) for row in rows)
    assert all(colors.reset in row for row in rows)


def test_banner_falls_back_to_the_wordmark_alone_on_a_narrow_terminal():
    right = art.wordmark(PLAIN)
    assert art.banner(right, columns=40, colors=PLAIN) == right
