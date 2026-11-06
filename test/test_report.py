"""Tests for bin/report.py: event lines, the progress line and the summary table."""

from __future__ import annotations

import io

import pytest
import report
from report import FAIL, OK, SAME, Listing, Reporter, Row

pytestmark = pytest.mark.usefixtures("no_color")


def test_event_columns_line_up_whatever_the_verb(capsys: pytest.CaptureFixture[str]):
    reporter = Reporter()
    reporter.event(OK, "updated", "feature", "2 new commits")
    reporter.event(report.PLAN, "would update", "other")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == ""  # the first event sets the list apart from the preamble
    assert lines[1] == "  ✓ updated       feature  2 new commits"
    assert lines[2] == "  ○ would update  other"
    assert lines[1].index("feature") == lines[2].index("other")


def test_progress_is_silent_off_a_terminal():
    stream = io.StringIO()
    with Reporter().progress(500, stream=stream) as progress:
        for index in range(500):
            progress.step(f"branch-{index}")
    assert progress.done == 500
    assert stream.getvalue() == ""


def test_progress_is_erased_before_an_event(capsys: pytest.CaptureFixture[str]):
    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    stream = Terminal()
    reporter = Reporter()
    with reporter.progress(3, stream=stream) as progress:
        progress.step("one")
        assert "[1/3] one" in stream.getvalue()
        reporter.event(OK, "updated", "one")
        assert stream.getvalue().endswith("\r\033[2K")
    assert "[1/3]" not in capsys.readouterr().out


def test_summary_caps_long_rows_and_counts_the_rest(capsys: pytest.CaptureFixture[str]):
    names = [f"branch-{index:04d}" for index in range(2500)]
    report.summary(
        "Summary",
        [
            Row(OK, "Updated", names[:1]),
            Row(SAME, "Up to date", names, Listing.COUNT),
            Row(OK, "Local only", names[:25]),
            Row(FAIL, "Blocked", [], Listing.ALL),
        ],
        facts=["2500 branches", "20s"],
    )
    out = capsys.readouterr().out
    assert "Summary  2500 branches · 20s" in out
    assert "  ✓ Updated        1   branch-0000" in out
    assert "  = Up to date  2500\n" in out
    assert "branch-2499" not in out
    assert out.count("branch-00") == 1 + report.LIST_LIMIT
    assert "… and 15 more" in out
    assert "Blocked" not in out  # empty rows are left out


def test_summary_lists_every_blocked_item(capsys: pytest.CaptureFixture[str]):
    blocked = [f"b{index}: rebase failed" for index in range(30)]
    report.summary("Summary", [Row(FAIL, "Blocked", blocked, Listing.ALL)])
    out = capsys.readouterr().out
    assert all(item in out for item in blocked)
    assert "more" not in out


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0.42, "0.4s"), (20.4, "20s"), (185, "3m 05s"), (3725, "1h 02m")],
)
def test_duration(seconds: float, text: str):
    assert report.duration(seconds) == text


def test_a_second_reporter_opens_its_own_list(capsys: pytest.CaptureFixture[str]):
    for _ in range(2):
        Reporter().event(OK, "updated", "feature")
    line = "  ✓ updated       feature"
    assert capsys.readouterr().out.splitlines() == ["", line, "", line]
