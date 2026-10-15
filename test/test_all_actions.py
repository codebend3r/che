"""Unit tests for the pure parts of ``bin/git/all-actions.py``.

Unlike most script suites here, these import the script rather than running it
as a subprocess. Everything worth testing - flattening two very different
GraphQL payloads into the same row shape, and picking which of a commit's
check suites to show - is pure data in, data out; driving it through ``gh``
would test GitHub, not us. The script's filename has a dash in it, so it is
loaded by path instead of by ``import``.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from conftest import load_script
from tui import display_width

all_actions = load_script("git/all-actions.py")


def suite(
    *,
    status: str = "COMPLETED",
    conclusion: str | None = "SUCCESS",
    workflow: str | None = "✅ Sanity check",
    created: str = "2026-09-09T03:01:13Z",
    updated: str = "2026-09-09T03:02:13Z",
    url: str = "https://github.com/codebend3r/che/actions/runs/1",
) -> dict:
    """One ``checkSuites`` node. ``workflow=None`` makes it a run-less suite."""
    run = None
    if workflow is not None:
        run = {
            "url": url,
            "createdAt": created,
            "updatedAt": updated,
            "workflow": {"name": workflow},
        }
    return {"status": status, "conclusion": conclusion, "workflowRun": run}


def branch_payload(*repos: dict) -> dict:
    return {"data": {"repositoryOwner": {"repositories": {"nodes": list(repos)}}}}


def repo(name: str, branch: str | None = "main", suites: list[dict] | None = None) -> dict:
    ref = None
    if branch is not None:
        ref = {"name": branch, "target": {"checkSuites": {"nodes": suites or []}}}
    return {"nameWithOwner": name, "defaultBranchRef": ref}


# -- pick_suite -----------------------------------------------------------


def test_pick_suite_ignores_suites_without_a_workflow_run():
    """Every repo in the wild carries several QUEUED suites whose workflowRun
    is null - GitHub creates them for apps that never dispatch a run. Showing
    one would report a permanent "queued" on a repo that is perfectly idle."""
    suites = [
        suite(status="QUEUED", conclusion=None, workflow=None),
        suite(status="QUEUED", conclusion=None, workflow=None),
        suite(workflow="✅ Sanity check"),
    ]
    assert all_actions.pick_suite(suites)["workflowRun"]["workflow"]["name"] == "✅ Sanity check"


def test_pick_suite_returns_none_when_nothing_has_a_run():
    assert all_actions.pick_suite([suite(workflow=None), suite(workflow=None)]) is None
    assert all_actions.pick_suite([]) is None


def test_pick_suite_prefers_in_flight_over_a_failure():
    suites = [
        suite(conclusion="FAILURE", workflow="old failure"),
        suite(status="IN_PROGRESS", conclusion=None, workflow="running now"),
        suite(conclusion="SUCCESS", workflow="fine"),
    ]
    assert all_actions.pick_suite(suites)["workflowRun"]["workflow"]["name"] == "running now"


def test_pick_suite_prefers_a_failure_over_a_success():
    suites = [
        suite(conclusion="SUCCESS", workflow="fine"),
        suite(conclusion="FAILURE", workflow="broken"),
    ]
    assert all_actions.pick_suite(suites)["workflowRun"]["workflow"]["name"] == "broken"


def test_pick_suite_breaks_a_createdat_tie_on_document_order():
    """GitHub stamps every run triggered by one push with the same second."""
    same = "2026-09-09T03:01:13Z"
    suites = [
        suite(workflow="first", created=same),
        suite(workflow="last", created=same),
    ]
    assert all_actions.pick_suite(suites)["workflowRun"]["workflow"]["name"] == "last"


# -- build_branch_rows ----------------------------------------------------


def test_build_branch_rows_reads_the_repo_and_its_default_branch():
    payload = branch_payload(repo("codebend3r/smeltr", "main", [suite(conclusion="FAILURE")]))
    (row,) = all_actions.build_branch_rows(payload)

    assert row.repo == "codebend3r/smeltr"
    assert row.branch == "main"
    assert row.run.status == "failure"
    assert row.run.live is False
    assert row.run.workflow == "✅ Sanity check"
    assert row.run.url.endswith("/runs/1")


def test_build_branch_rows_reports_the_real_default_branch_name():
    """Around a dozen of these repos still default to `master`. The sweep is
    over each repo's DEFAULT branch, so the column shows whatever it is called
    rather than claiming everything is `main`."""
    payload = branch_payload(repo("codebend3r/jtron", "master", [suite()]))
    (row,) = all_actions.build_branch_rows(payload)
    assert row.branch == "master"


def test_build_branch_rows_skips_repos_with_no_run_on_the_tip_commit():
    """Most owned repos have no CI at all. Rendering them as `none` rows would
    bury the handful that do."""
    payload = branch_payload(
        repo("codebend3r/has-ci", "main", [suite()]),
        repo("codebend3r/no-suites", "main", []),
        repo("codebend3r/only-null-runs", "main", [suite(workflow=None)]),
        repo("codebend3r/empty-repo", branch=None),
    )
    assert [r.repo for r in all_actions.build_branch_rows(payload)] == ["codebend3r/has-ci"]


def test_build_branch_rows_marks_an_in_flight_run_live():
    payload = branch_payload(
        repo("codebend3r/che", "main", [suite(status="IN_PROGRESS", conclusion=None)])
    )
    (row,) = all_actions.build_branch_rows(payload)
    assert row.run.live is True
    assert row.run.status == "in_progress"


def test_build_branch_rows_names_a_null_status_rather_than_blanking_the_cell():
    payload = branch_payload(repo("codebend3r/che", "main", [suite(conclusion=None)]))
    (row,) = all_actions.build_branch_rows(payload)
    assert row.run.status == "unknown"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": {}},
        {"data": {"repositoryOwner": None}},
        {"data": {"repositoryOwner": {"repositories": {"nodes": None}}}},
        branch_payload(None),
    ],
)
def test_build_branch_rows_survives_a_thin_payload(payload):
    """A missing scope or a rate-limited call returns data with nulls in it.
    In --watch mode that must skip a cycle, not end the run."""
    assert all_actions.build_branch_rows(payload) == []


# -- build_rows ------------------------------------------------------------


def pr_payload(*prs: dict) -> dict:
    return {"data": {"search": {"nodes": list(prs)}}}


def pull_request(number: int, suites: list[dict]) -> dict:
    return {
        "number": number,
        "url": f"https://github.com/codebend3r/che/pull/{number}",
        "headRefName": "feat/actions",
        "repository": {"nameWithOwner": "codebend3r/che"},
        "commits": {"nodes": [{"commit": {"checkSuites": {"nodes": suites}}}]},
    }


def test_build_rows_shapes_a_pr_row():
    (row,) = all_actions.build_rows(pr_payload(pull_request(12, [suite()])))

    assert row.repo == "codebend3r/che"
    assert row.number == 12
    assert row.branch == "feat/actions"
    assert row.run.status == "success"
    assert row.run.workflow == "✅ Sanity check"


def test_build_rows_falls_back_to_the_pr_url_when_nothing_has_run():
    """A PR row with no run still links somewhere useful - unlike a repo row,
    which is dropped instead."""
    (row,) = all_actions.build_rows(pr_payload(pull_request(12, [])))

    assert row.run == all_actions.NO_RUN._replace(url="https://github.com/codebend3r/che/pull/12")


def test_build_rows_skips_a_node_that_is_not_a_pull_request():
    assert all_actions.build_rows(pr_payload(None, {})) == []


# -- run_duration ---------------------------------------------------------


def iso(seconds_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def a_run(*, live: bool, created: str, updated: str) -> all_actions.Run:
    return all_actions.NO_RUN._replace(live=live, created=created, updated=updated)


def test_run_duration_of_a_finished_run_is_created_to_updated():
    finished = a_run(live=False, created="2026-09-09T03:01:13Z", updated="2026-09-09T03:02:23Z")
    assert all_actions.run_duration(finished) == "1m10s"


def test_run_duration_of_a_live_run_ticks_against_now():
    assert all_actions.run_duration(a_run(live=True, created=iso(7200), updated=iso(7190))) == (
        "2h00m"
    )


def test_a_null_status_suite_is_live_and_its_duration_ticks():
    """A suite that is not COMPLETED but has no status is shown as "unknown".
    It is still in flight, so TOOK must keep counting rather than freeze at
    whenever GitHub last touched it."""
    payload = branch_payload(
        repo("codebend3r/che", "main", [suite(status=None, created=iso(7200), updated=iso(7190))])
    )
    (row,) = all_actions.build_branch_rows(payload)

    assert row.run.live is True
    assert row.run.status == "unknown"
    assert all_actions.run_duration(row.run) == "2h00m"


# -- draw_table -----------------------------------------------------------


def make_row(repo: str = "che", **run_fields) -> all_actions.Row:
    """A default-branch row for ``repo``, its run a success unless overridden."""
    run = all_actions.NO_RUN._replace(**{"status": "success", **run_fields})
    return all_actions.Row(repo=repo, branch="main", run=run)


STATUS_COLUMNS = (
    ("REPO", lambda r: r.repo, 4),
    ("WORKFLOW", lambda r: r.run.workflow, 8),
    ("STATUS", lambda r: r.run.status, 6),
)


def status_columns(out: str) -> set[int]:
    """The terminal column each data row's status starts at."""
    lines = out.splitlines()[1:]
    return {
        display_width(line[: line.index("failure" if "failure" in line else "success")])
        for line in lines
    }


def test_draw_table_aligns_columns_around_double_width_emoji(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    rows = [
        make_row(repo="smeltr", status="failure", workflow="🩺 Main sanity check"),
        make_row(repo="court-vision", status="success", workflow="✅ Sanity check"),
    ]

    all_actions.draw_table(rows, STATUS_COLUMNS)

    out = capsys.readouterr().out
    assert len(status_columns(out)) == 1, f"status column is ragged: {out}"


def test_draw_table_counts_a_neutral_emoji_as_two_columns(capsys, monkeypatch):
    """🗑 (U+1F5D1) is East Asian Width "neutral", yet every terminal draws it
    two columns wide. Measured as one, its row's later cells sat a column left
    of every other row's."""
    monkeypatch.setenv("NO_COLOR", "1")
    rows = [
        make_row(status="failure", workflow="🗑 Cleanup"),
        make_row(status="success", workflow="Lint"),
    ]

    all_actions.draw_table(rows, STATUS_COLUMNS)

    out = capsys.readouterr().out
    assert len(status_columns(out)) == 1, f"status column is ragged: {out}"


def test_draw_table_honours_the_minimum_column_width(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    all_actions.draw_table(
        [make_row(repo="a")], (("REPO", lambda r: r.repo, 4), ("X", lambda r: "x", 1))
    )

    header, line = capsys.readouterr().out.splitlines()
    assert header.startswith("REPO")
    # "a" padded to the 4-wide minimum, then the two-space gutter.
    assert line.startswith("a     x")


def test_draw_table_links_the_first_column_to_the_run(capsys, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    url = "https://github.com/codebend3r/che/actions/runs/1"
    columns = (("REPO", lambda r: r.repo, 4), ("BRANCH", lambda r: r.branch, 6))

    all_actions.draw_table([make_row(repo="linked", url=url), make_row(repo="plain")], columns)

    _, linked, plain = capsys.readouterr().out.splitlines()
    assert f"\033]8;;{url}\033\\linked\033]8;;\033\\" in linked
    # No URL, no escape: tui.hyperlink would wrap even an empty one.
    assert "\033]8;;" not in plain


def test_draw_table_is_plain_text_when_colour_is_off(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    all_actions.draw_table([make_row(url="https://example.com")], STATUS_COLUMNS)

    assert "\033" not in capsys.readouterr().out


# -- gh_graphql / render --------------------------------------------------


def test_gh_graphql_passes_variables_and_parses_the_reply(monkeypatch):
    seen = []

    def fake_run(argv, **_):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout='{"data": {}}')

    monkeypatch.setattr(all_actions, "run", fake_run)

    assert all_actions.gh_graphql("QUERY", 5, login="codebend3r") == {"data": {}}
    (argv,) = seen
    assert argv[:3] == ["gh", "api", "graphql"]
    assert "first=5" in argv
    assert "login=codebend3r" in argv


@pytest.mark.parametrize(("code", "stdout"), [(1, '{"data": {}}'), (0, "<html>rate limited")])
def test_gh_graphql_reads_a_failure_as_no_data(monkeypatch, code, stdout):
    monkeypatch.setattr(
        all_actions,
        "run",
        lambda argv, **_: subprocess.CompletedProcess(argv, code, stdout=stdout),
    )
    assert all_actions.gh_graphql("QUERY", 5) == {}


def fake_gh(calls: list[dict]):
    """A gh_graphql stand-in: one PR, and one default-branch repo per login."""

    def _gh(query, first, **variables):
        calls.append(variables)
        if "login" in variables:
            login = variables["login"]
            return branch_payload(repo(f"{login}/site", "main", [suite()]))
        return pr_payload(pull_request(7, [suite()]))

    return _gh


def test_render_asks_once_for_prs_and_once_per_owner(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    calls: list[dict] = []
    monkeypatch.setattr(all_actions, "gh_graphql", fake_gh(calls))

    all_actions.render(("alice", "bob"), "alice", 100, 100, True)

    (search,) = [c["q"] for c in calls if "q" in c]
    assert "author:alice" in search
    assert "user:alice user:bob" in search
    assert sorted(c["login"] for c in calls if "login" in c) == ["alice", "bob"]
    out = capsys.readouterr().out
    # Two owners, so repos keep their owner prefix.
    assert "alice/site" in out
    assert "bob/site" in out


def test_render_drops_the_owner_prefix_for_a_single_owner(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(all_actions, "gh_graphql", fake_gh([]))

    all_actions.render(("alice",), "alice", 100, 100, True)

    out = capsys.readouterr().out
    assert "alice/site" not in out
    assert "site" in out


def test_render_skips_the_owner_sweep_with_no_main(monkeypatch, capsys):
    monkeypatch.setenv("NO_COLOR", "1")
    calls: list[dict] = []
    monkeypatch.setattr(all_actions, "gh_graphql", fake_gh(calls))

    all_actions.render(("alice", "bob"), "alice", 100, 100, False)

    assert [c for c in calls if "login" in c] == []
    assert "default branch" not in capsys.readouterr().out


def test_render_with_nothing_to_show_says_so_in_both_sections(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(all_actions, "gh_graphql", lambda query, first, **variables: {})

    all_actions.render(("alice", "bob"), "alice", 100, 100, True)

    out = capsys.readouterr().out
    assert "0 open PR(s)" in out
    assert "No open pull requests authored by alice under: alice,bob" in out
    assert "No default-branch runs found under: alice,bob" in out
    assert "Nothing in flight" in out


# -- main -----------------------------------------------------------------


def test_a_bad_watch_value_names_watch(fake_bin, run_script):
    """It overrides --interval, so the error used to name the wrong flag."""
    fake_bin("gh", "exit 0\n")

    result = run_script("git/all-actions.py", ["--watch=abc"])

    assert result.returncode == 1
    assert "--watch must be a non-negative integer (got: abc)" in result.stdout
