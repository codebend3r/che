"""Tests for bin/report.py: event lines, the progress line and the summary table."""

from __future__ import annotations

import io

import pytest
import report
from report import FAIL, OK, SAME, Progress, Row


@pytest.fixture(autouse=True)
def plain(no_color: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # Each test starts as if nothing has been printed yet.
    monkeypatch.setattr(report, "_opened", False)
    monkeypatch.setattr(report, "_active", None)


def test_event_columns_line_up_whatever_the_verb(capsys: pytest.CaptureFixture[str]):
    report.event(OK, "updated", "feature", "2 new commits")
    report.event(report.PLAN, "would update", "other")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == ""  # the first event sets the list apart from the preamble
    assert lines[1] == "  ✓ updated       feature  2 new commits"
    assert lines[2] == "  ○ would update  other"
    assert lines[1].index("feature") == lines[2].index("other")


def test_progress_is_silent_off_a_terminal():
    stream = io.StringIO()
    with Progress(500, stream=stream) as progress:
        for index in range(500):
            progress.step(f"branch-{index}")
    assert progress.done == 500
    assert stream.getvalue() == ""


def test_progress_is_erased_before_an_event(capsys: pytest.CaptureFixture[str]):
    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    stream = Terminal()
    with Progress(3, stream=stream) as progress:
        progress.step("one")
        assert "[1/3] one" in stream.getvalue()
        report.event(OK, "updated", "one")
        assert stream.getvalue().endswith("\r\033[2K")
    assert "[1/3]" not in capsys.readouterr().out


def test_summary_caps_long_rows_and_counts_the_rest(capsys: pytest.CaptureFixture[str]):
    names = [f"branch-{index:04d}" for index in range(2500)]
    report.summary(
        "Summary",
        [
            Row(OK, "Updated", names[:1]),
            Row(SAME, "Up to date", names, listed=False),
            Row(OK, "Local only", names[:25]),
            Row(FAIL, "Blocked", [], limit=None),
        ],
        facts=["2500 branches", "20s"],
    )
    out = capsys.readouterr().out
    assert "Summary  2500 branches · 20s" in out
    assert "  ✓ Updated        1   branch-0000" in out
    assert "  = Up to date  2500\n" in out
    assert "branch-2499" not in out
    assert out.count("branch-00") == 1 + report.DEFAULT_LIMIT
    assert "… and 15 more" in out
    assert "Blocked" not in out  # empty rows are left out


def test_summary_lists_every_blocked_item(capsys: pytest.CaptureFixture[str]):
    blocked = [f"b{index}: rebase failed" for index in range(30)]
    report.summary("Summary", [Row(FAIL, "Blocked", blocked, limit=None)])
    out = capsys.readouterr().out
    assert all(item in out for item in blocked)
    assert "more" not in out


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0.42, "0.4s"), (20.4, "20s"), (185, "3m 05s"), (3725, "1h 02m")],
)
def test_duration(seconds: float, text: str):
    assert report.duration(seconds) == text
