"""Unit tests for the pure parts of ``bin/git/all-actions.py``.

Unlike most script suites here, these import the script rather than running it
as a subprocess. Everything worth testing - flattening two very different
GraphQL payloads into the same row shape, and picking which of a commit's
check suites to show - is pure data in, data out; driving it through ``gh``
would test GitHub, not us. The script's filename has a dash in it, so it is
loaded by path instead of by ``import``.
"""

from __future__ import annotations

import importlib.util

import pytest
from conftest import BIN


def _load_script(name: str, relative: str):
    path = BIN / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


all_actions = _load_script("all_actions", "git/all-actions.py")


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

    assert row["repo"] == "codebend3r/smeltr"
    assert row["branch"] == "main"
    assert row["status"] == "failure"
    assert row["live"] is False
    assert row["workflow"] == "✅ Sanity check"
    assert row["url"].endswith("/runs/1")


def test_build_branch_rows_reports_the_real_default_branch_name():
    """Around a dozen of these repos still default to `master`. The sweep is
    over each repo's DEFAULT branch, so the column shows whatever it is called
    rather than claiming everything is `main`."""
    payload = branch_payload(repo("codebend3r/jtron", "master", [suite()]))
    (row,) = all_actions.build_branch_rows(payload)
    assert row["branch"] == "master"


def test_build_branch_rows_skips_repos_with_no_run_on_the_tip_commit():
    """Most owned repos have no CI at all. Rendering them as `none` rows would
    bury the handful that do."""
    payload = branch_payload(
        repo("codebend3r/has-ci", "main", [suite()]),
        repo("codebend3r/no-suites", "main", []),
        repo("codebend3r/only-null-runs", "main", [suite(workflow=None)]),
        repo("codebend3r/empty-repo", branch=None),
    )
    assert [r["repo"] for r in all_actions.build_branch_rows(payload)] == ["codebend3r/has-ci"]


def test_build_branch_rows_marks_an_in_flight_run_live():
    payload = branch_payload(
        repo("codebend3r/che", "main", [suite(status="IN_PROGRESS", conclusion=None)])
    )
    (row,) = all_actions.build_branch_rows(payload)
    assert row["live"] is True
    assert row["status"] == "in_progress"


def test_build_branch_rows_names_a_null_status_rather_than_blanking_the_cell():
    payload = branch_payload(repo("codebend3r/che", "main", [suite(conclusion=None)]))
    (row,) = all_actions.build_branch_rows(payload)
    assert row["status"] == "unknown"


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


# -- build_rows (the PR path, unchanged by the refactor) -------------------


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

    assert row["repo"] == "codebend3r/che"
    assert row["number"] == 12
    assert row["branch"] == "feat/actions"
    assert row["status"] == "success"
    assert row["workflow"] == "✅ Sanity check"


def test_build_rows_falls_back_to_the_pr_url_when_nothing_has_run():
    """A PR row with no run still links somewhere useful - unlike a repo row,
    which is dropped instead."""
    (row,) = all_actions.build_rows(pr_payload(pull_request(12, [])))

    assert row["status"] == "none"
    assert row["workflow"] == "-"
    assert row["url"].endswith("/pull/12")


def test_build_rows_skips_a_node_that_is_not_a_pull_request():
    assert all_actions.build_rows(pr_payload(None, {})) == []


# -- draw_table -----------------------------------------------------------


def test_draw_table_aligns_columns_around_double_width_emoji(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    rows = [
        {"repo": "smeltr", "status": "failure", "workflow": "🩺 Main sanity check", "url": ""},
        {"repo": "court-vision", "status": "success", "workflow": "✅ Sanity check", "url": ""},
    ]
    columns = (
        ("REPO", lambda r: r["repo"], 4),
        ("WORKFLOW", lambda r: r["workflow"], 8),
        ("STATUS", lambda r: r["status"], 6),
    )

    all_actions.draw_table(rows, columns, lambda r: "")

    lines = capsys.readouterr().out.splitlines()
    starts = [line.index("failure" if "failure" in line else "success") for line in lines[1:]]
    assert len(set(starts)) == 1, f"status column is ragged: {lines}"


def test_draw_table_honours_the_minimum_column_width(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    rows = [{"repo": "a", "url": ""}]
    all_actions.draw_table(rows, (("REPO", lambda r: r["repo"], 4), ("X", lambda r: "x", 1)), None)

    header, row = capsys.readouterr().out.splitlines()
    assert header.startswith("REPO")
    # "a" padded to the 4-wide minimum, then the two-space gutter.
    assert row.startswith("a     x")
