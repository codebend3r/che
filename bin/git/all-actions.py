#!/usr/bin/env python3
"""🎬 Show the latest GitHub Actions run per open PR and per default branch.

Two tables. The first is one row per open PR you authored, so a repo with five
open PRs gets five rows. The second is one row per repo you own, showing the
run on its default branch - the sanity checks and anything else that fires on
a push to main. The repo name is a terminal hyperlink to that run.

When a commit has several workflow runs, the row shows the one worth acting
on: anything still in flight, else a failure, else the most recent run.

Usage:
  all-actions.py [--owner=NAME[,NAME...]] [--author=NAME] [--pr-limit=N]
                 [--repo-limit=N] [--no-main]
                 [--watch[=SECONDS]] [--interval=SECONDS]

Options:
  --owner=NAME       Owner(s) to scan, comma-separated (default: your gh login)
  --author=NAME      PR author to match (default: your gh login)
  --pr-limit=N       Open PRs to inspect, max 100 (default: 100)
  --repo-limit=N     Repos to sweep for default-branch runs, max 100 (default: 100)
  --no-main          Skip the default-branch table, showing PRs only
  --interval=SECONDS Refresh interval used by --watch (default: 15)
  --watch[=SECONDS]  Refresh every interval until interrupted
  --help             Show help
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Cell widths come from tui's unicodedata-based measure, which replaced the
# shell's count of 4-byte UTF-8 sequences and its hand-kept list of wide emoji.
from tui import display_width, hyperlink
from utils import (
    CYAN,
    GREEN,
    NC,
    RED,
    YELLOW,
    add_bool_flag,
    build_parser,
    heading,
    info,
    log_color,
    note,
    parse_count,
    require_binary,
    run,
    run_cli,
    run_output,
    success,
    warning,
)

__version__ = "2.2.0"

# (icon, row colour) per status; see status_style for one not listed here.
STATUS_STYLE = {
    "in_progress": ("🔄", CYAN),
    "queued": ("⏳", YELLOW),
    "waiting": ("⏳", YELLOW),
    "pending": ("⏳", YELLOW),
    "requested": ("⏳", YELLOW),
    "success": ("✅", GREEN),
    "failure": ("❌", RED),
    "timed_out": ("❌", RED),
    "startup_failure": ("❌", RED),
    "action_required": ("⚪", RED),
    "cancelled": ("🚫", NC),
    "skipped": ("⏩", NC),
    "none": ("➖", NC),  # noqa: RUF001
}


def status_style(status: str) -> tuple[str, str]:
    """The (icon, row colour) for ``status``, neutral for one GitHub adds later."""
    return STATUS_STYLE.get(status, ("⚪", NC))


BAD_CONCLUSIONS = frozenset({"FAILURE", "TIMED_OUT", "STARTUP_FAILURE"})

# The check suites both queries read off a commit, so a PR's head commit and a
# repo's default-branch tip come back in the same shape (see suite_run).
RUN_SUITES = """
fragment RunSuites on Commit {
  checkSuites(first: 20) {
    nodes {
      status
      conclusion
      workflowRun {
        url
        createdAt
        updatedAt
        workflow { name }
      }
    }
  }
}
"""

# Every open PR and its head-commit check suites, in a single call: one call
# keeps a 15-second refresh well inside the rate limit.
GRAPHQL_QUERY = (
    """
query($q: String!, $first: Int!) {
  search(query: $q, type: ISSUE, first: $first) {
    nodes {
      ... on PullRequest {
        number
        url
        headRefName
        repository { nameWithOwner }
        commits(last: 1) {
          nodes {
            commit { ...RunSuites }
          }
        }
      }
    }
  }
}
"""
    + RUN_SUITES
)


# The default-branch sweep. `repositoryOwner` takes one login, unlike the
# search query's `user:` qualifiers, so this runs once per --owner - one call
# per owner rather than one per repo: sweeping fifty repos through the REST
# API would be fifty calls a cycle, which a 15-second --watch would spend the
# whole rate limit on.
#
# `isFork: false, isArchived: false` on purpose: a fork's CI belongs to whoever
# you forked from, and an archived repo cannot have a run you would act on.
# PUSHED_AT ordering means a --repo-limit below the account's repo count keeps
# the repos you actually touch.
BRANCH_GRAPHQL_QUERY = (
    """
query($login: String!, $first: Int!) {
  repositoryOwner(login: $login) {
    repositories(
      first: $first
      isFork: false
      isArchived: false
      ownerAffiliations: [OWNER]
      orderBy: {field: PUSHED_AT, direction: DESC}
    ) {
      nodes {
        nameWithOwner
        defaultBranchRef {
          name
          target { ...RunSuites }
        }
      }
    }
  }
}
"""
    + RUN_SUITES
)


class Run(NamedTuple):
    """The workflow run a row shows."""

    live: bool  # still in flight; decides sort order and how TOOK is measured
    status: str
    workflow: str
    created: str
    updated: str
    url: str


# A PR whose head commit has no run yet. It still links to the PR itself.
NO_RUN = Run(live=False, status="none", workflow="-", created="", updated="", url="")


class Row(NamedTuple):
    """One table row: a PR's head commit, or a repo's default-branch tip."""

    repo: str
    branch: str
    run: Run
    number: int | None = None  # the PR; None on a default-branch row


def pad(value: str, width: int, url: str = "") -> str:
    """Left-align ``value`` in a cell ``width`` terminal columns wide.

    With a ``url`` the text is wrapped in an OSC 8 hyperlink. The escapes are
    zero-width, so the padding is computed from the plain text and only the
    text itself gets wrapped. ``hyperlink`` drops them alongside colour, so a
    piped or NO_COLOR run is plain text throughout.
    """
    padding = " " * max(0, width - display_width(value))
    return (hyperlink(value, url) if url else value) + padding


def parse_iso(value: str) -> datetime | None:
    """Parse GitHub's ISO-8601 UTC timestamps, or None if absent/unparseable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_to_age(value: str) -> str:
    """Compact age since ``value``: "45s", "12m", "3h", "2d"."""
    then = parse_iso(value)
    if then is None:
        return "-"

    delta = max(0, int((datetime.now(UTC) - then).total_seconds()))
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


def fmt_duration(seconds: int) -> str:
    """Compact duration: "45s", "2m10s", "1h04m"."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def run_duration(run: Run) -> str:
    """How long a run took.

    Completed runs are createdAt -> updatedAt; anything still in flight is
    measured against now, so the column ticks up while it runs. ``live`` is
    the run's own flag, so a suite whose status came back null - shown as
    "unknown", but not COMPLETED - ticks too, rather than reading as finished.
    """
    start = parse_iso(run.created)
    if start is None:
        return "-"

    end = datetime.now(UTC) if run.live else parse_iso(run.updated)
    if end is None:
        return "-"

    return fmt_duration(max(0, int((end - start).total_seconds())))


def pick_suite(suites: list[dict]) -> dict | None:
    """The check suite worth showing: in flight, else failed, else newest."""
    usable = [s for s in suites if s.get("workflowRun")]
    if not usable:
        return None

    def created(suite: dict) -> str:
        return suite["workflowRun"].get("createdAt") or ""

    # sorted(...)[-1], not max(...): jq's `sort_by | last` is a stable sort, so
    # for suites sharing a createdAt it returns the LAST in document order,
    # where max() returns the first. GitHub stamps every workflow run triggered
    # by one push with the same second, so this tie fires constantly.
    live = [s for s in usable if s.get("status") != "COMPLETED"]
    if live:
        return sorted(live, key=created)[-1]

    bad = [s for s in usable if (s.get("conclusion") or "") in BAD_CONCLUSIONS]
    if bad:
        return sorted(bad, key=created)[-1]

    return sorted(usable, key=created)[-1]


def suite_run(suite: dict) -> Run:
    """The :class:`Run` one check suite (from :func:`pick_suite`) describes.

    Shared by both queries: a PR's head commit and a repo's default-branch tip
    return the same ``checkSuites`` shape, so they render from the same code.
    """
    workflow_run = suite["workflowRun"]
    live = suite.get("status") != "COMPLETED"
    # `or "unknown"`: jq died outright on a null status, taking the whole
    # run's output with it. An empty cell would be worse than saying so.
    status = (suite.get("status") if live else suite.get("conclusion")) or "unknown"

    return Run(
        live=live,
        status=status.lower(),
        workflow=((workflow_run.get("workflow") or {}).get("name")) or "-",
        created=workflow_run.get("createdAt") or "",
        updated=workflow_run.get("updatedAt") or "",
        url=workflow_run.get("url") or "",
    )


def build_rows(payload: dict) -> list[Row]:
    """Flatten the GraphQL response into one row per PR.

    This replaces the shell version's jq program, which is why jq is no longer
    a dependency.
    """
    rows = []
    nodes = (payload.get("data", {}).get("search", {}) or {}).get("nodes") or []

    for pr in nodes:
        if not pr or pr.get("number") is None:
            continue

        commits = (pr.get("commits") or {}).get("nodes") or []
        suites: list[dict] = []
        if commits:
            commit = (commits[0] or {}).get("commit") or {}
            suites = ((commit.get("checkSuites") or {}).get("nodes")) or []

        # A PR with no run still links somewhere useful, so it keeps its row.
        # A repo with no run does not - see build_branch_rows.
        suite = pick_suite(suites)
        rows.append(
            Row(
                repo=(pr.get("repository") or {}).get("nameWithOwner") or "",
                branch=pr.get("headRefName") or "",
                run=suite_run(suite) if suite else NO_RUN._replace(url=pr.get("url") or ""),
                number=pr["number"],
            )
        )

    return rows


def build_branch_rows(payload: dict) -> list[Row]:
    """Flatten the repository response into one row per default branch.

    Repos whose default-branch tip has no workflow run are dropped rather than
    shown as a "none" row: an account owns far more repos without CI than with
    it, and thirty empty rows would bury the handful worth looking at.

    The branch shown is each repo's DEFAULT branch, whatever it is named -
    plenty of older repos still default to `master`, and their sanity checks
    are as worth seeing as anything on `main`.
    """
    rows = []
    owner = (payload.get("data") or {}).get("repositoryOwner") or {}
    nodes = (owner.get("repositories") or {}).get("nodes") or []

    for repo in nodes:
        if not repo:
            continue

        ref = repo.get("defaultBranchRef") or {}
        target = ref.get("target") or {}
        suites = ((target.get("checkSuites") or {}).get("nodes")) or []

        suite = pick_suite(suites)
        if suite is None:
            continue

        rows.append(
            Row(
                repo=repo.get("nameWithOwner") or "",
                branch=ref.get("name") or "",
                run=suite_run(suite),
            )
        )

    return rows


def gh_graphql(query: str, first: int, **variables: str) -> dict:
    """One ``gh api graphql`` call, or ``{}`` when it fails or is not JSON.

    ``{}`` flattens to no rows. One bad owner (a typo, an org you lost access
    to) or one failed cycle of a --watch must not sink the rest of the sweep.
    """
    argv = ["gh", "api", "graphql", "-f", f"query={query}", "-F", f"first={first}"]
    for name, value in variables.items():
        argv += ["-f", f"{name}={value}"]

    completed = run(argv, check=False, capture=True)
    if completed.returncode != 0:
        return {}
    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def sort_rows(rows: list[Row]) -> None:
    """In-flight rows first, then grouped by repo, newest run first.

    Two passes because Python's sort is stable: the second preserves the
    ordering the first established within each group.
    """
    rows.sort(key=lambda r: r.run.created, reverse=True)
    rows.sort(key=lambda r: (not r.run.live, r.repo))


def draw_table(rows: list[Row], columns: Sequence[tuple[str, Callable[[Row], str], int]]) -> None:
    """Print one aligned table of ``rows``.

    ``columns`` is (title, cell, minimum width) per column; every column is
    sized to its widest cell. The first column, the repo name in both tables,
    links to the row's run.

    Factored out when the default-branch table arrived: it shares every column
    but PR with the pull request table, and two copies of the width arithmetic
    would drift the moment either grew a column.
    """
    widths = [
        max([minimum, *(display_width(cell(row)) for row in rows)]) for _, cell, minimum in columns
    ]
    last = len(columns) - 1

    # The header's final cell is not padded, so the line has no trailing
    # whitespace; data cells are, matching what the shell version emitted.
    header = "  ".join(
        title if index == last else pad(title, width)
        for index, ((title, _, _), width) in enumerate(zip(columns, widths, strict=True))
    )
    success(header)

    for row in rows:
        line = "  ".join(
            pad(cell(row), width, row.run.url if index == 0 else "")
            for index, ((_, cell, _), width) in enumerate(zip(columns, widths, strict=True))
        )
        log_color(status_style(row.run.status)[1], line)


def render(
    owners: tuple[str, ...], author: str, pr_limit: int, repo_limit: int, include_main: bool
) -> None:
    """Draw both tables once."""
    owners_text = ",".join(owners)
    # `user:` qualifiers are OR'd by GitHub search, so several owners widen the
    # sweep rather than narrowing it.
    search = " ".join(
        ["is:pr is:open archived:false", f"author:{author}", *(f"user:{o}" for o in owners)]
    )

    # The PR search and each owner's sweep in parallel: run one after another,
    # every --watch cycle waited on 1 + N round trips back to back.
    with ThreadPoolExecutor() as pool:
        pr_payload = pool.submit(gh_graphql, GRAPHQL_QUERY, pr_limit, q=search)
        branch_payloads = [
            pool.submit(gh_graphql, BRANCH_GRAPHQL_QUERY, repo_limit, login=owner)
            for owner in (owners if include_main else ())
        ]
        rows = build_rows(pr_payload.result())
        # Collected in submission order, not as each call finishes, so the
        # output never depends on which reply happened to land first.
        branch_rows = [row for f in branch_payloads for row in build_branch_rows(f.result())]

    # After the fetch, not before: the shell called date(1) inside the banner,
    # so in --watch mode the timestamp reflects when the data landed.
    clock = datetime.now().strftime("%H:%M:%S")

    sort_rows(rows)
    sort_rows(branch_rows)

    single_owner = len(owners) == 1

    def label(row: Row) -> str:
        return row.repo.split("/", 1)[-1] if single_owner else row.repo

    # Every column but PR is shared: a push to the default branch has no pull
    # request behind it, and a column of dashes would just take width from
    # the workflow names, which are the point of that table.
    repo_column = ("REPO", label, 4)
    run_columns = (
        ("STATUS", lambda r: f"{status_style(r.run.status)[0]} {r.run.status}", 6),
        ("WORKFLOW", lambda r: r.run.workflow, 8),
        ("BRANCH", lambda r: r.branch, 6),
        ("AGE", lambda r: iso_to_age(r.run.created), 4),
        ("TOOK", lambda r: run_duration(r.run), 5),
    )

    repo_count = len({r.repo for r in rows})
    heading(f"🎬  all-actions — {len(rows)} open PR(s) · {repo_count} repo(s) · {clock}")

    if rows:
        draw_table(rows, (repo_column, ("PR", lambda r: f"#{r.number}", 3), *run_columns))
    else:
        info(f"🫙 No open pull requests authored by {author} under: {owners_text}")

    if include_main:
        print(flush=True)
        note(f"🌳  default branch — {len(branch_rows)} repo(s)")
        if branch_rows:
            draw_table(branch_rows, (repo_column, *run_columns))
        else:
            info(f"🫙 No default-branch runs found under: {owners_text}")

    total = len(rows) + len(branch_rows)
    live_count = sum(1 for row in (*rows, *branch_rows) if row.run.live)
    idle_count = total - live_count

    print(flush=True)
    if live_count == 0:
        success(f"😴 Nothing in flight — {idle_count} run(s) showing their last result.")
    else:
        success(f"═══ {live_count} in flight · {idle_count} settled (last run) ═══")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="all-actions",
        description=(
            "🎬 Show the latest GitHub Actions run per open pull request and per\n"
            "   default branch, across every repo you own.\n\n"
            "   The first table is one row per open PR you authored, so a repo with\n"
            "   five open PRs gets five rows. The second is one row per repo, showing\n"
            "   the run on its default branch - the sanity checks and anything else\n"
            "   that fires on a push to main. Pass --no-main to skip it. The repo\n"
            "   name is a terminal hyperlink to that run.\n\n"
            "   When a commit has several workflow runs, the row shows the one worth\n"
            "   acting on: anything still in flight, else a failure, else the most\n"
            "   recent run."
        ),
    )
    parser.add_argument(
        "--owner",
        default="",
        metavar="NAME",
        help="Owner(s) to scan, comma-separated (default: your gh login)",
    )
    parser.add_argument(
        "--author",
        default="",
        metavar="NAME",
        help="PR author to match (default: your gh login)",
    )
    parser.add_argument(
        "--pr-limit",
        default="100",
        metavar="N",
        help="Open PRs to inspect, max 100 (default: 100)",
    )
    parser.add_argument(
        "--repo-limit",
        default="100",
        metavar="N",
        help="Repos to sweep for default-branch runs, max 100 (default: 100)",
    )
    # allow_value=False, per the convention for inverted flags: `--no-main=false`
    # is a double negative nobody should have to decode.
    add_bool_flag(
        parser,
        "--no-main",
        help="Skip the default-branch table, showing pull requests only",
        allow_value=False,
    )
    parser.add_argument(
        "--interval",
        default="15",
        metavar="SECONDS",
        help="Refresh interval used by --watch (default: 15)",
    )
    # --watch is special: it is both a bare flag and a flag that carries the
    # interval, so it cannot use add_bool_flag. nargs="?" also accepts the
    # space form `--watch 30`, which the shell version rejected.
    parser.add_argument(
        "--watch",
        nargs="?",
        const="",
        default=None,
        metavar="SECONDS",
        help="Refresh every interval until interrupted",
    )
    args = parser.parse_args(argv)

    # After parsing, unlike the shell version, so --help works without gh.
    require_binary("gh", hint="Install it with `brew install gh`.")

    # Both GraphQL connections cap out at 100 nodes per page.
    pr_limit = min(100, max(1, parse_count(args.pr_limit, "--pr-limit")))
    repo_limit = min(100, max(1, parse_count(args.repo_limit, "--repo-limit")))
    # A value given to --watch overrides --interval, so an error names it.
    interval_flag = "--watch" if args.watch else "--interval"
    interval = max(1, parse_count(args.watch or args.interval, interval_flag))
    watch = args.watch is not None
    include_main = not args.no_main

    if run(["gh", "auth", "status"], check=False, capture=True).returncode != 0:
        warning("❌ Not logged in to GitHub. Run: gh auth login")
        return 1

    owners_text = args.owner
    author = args.author
    if not owners_text or not author:
        login = run_output(["gh", "api", "user", "--jq", ".login"], check=False).strip()
        if not login:
            # Without a login the query loses its `user:` qualifier entirely and
            # silently searches all of GitHub. A token can pass `gh auth status`
            # and still fail here (missing read:user, unauthorised SSO, a 5xx).
            warning("❌ Could not determine your gh login. Pass --owner= and --author=.")
            return 1
        owners_text = owners_text or login
        author = author or login

    owners = tuple(owner for part in owners_text.split(",") if (owner := part.strip()))

    def draw() -> None:
        render(owners, author, pr_limit, repo_limit, include_main)

    if not watch:
        draw()
        return 0

    try:
        while True:
            # ANSI clear + home, rather than shelling out to clear(1).
            print("\033[2J\033[H", end="", flush=True)
            try:
                draw()
            # Broad on purpose: the shell wrapped this as `render || true`.
            except Exception as exc:
                # One unexpected payload shape must not end a long watch.
                warning(f"⚠️  Render failed, retrying next cycle: {exc}")
            info(f"🔁 Refreshing every {interval}s — Ctrl-C to stop.")
            time.sleep(interval)
    except KeyboardInterrupt:
        # Ctrl-C during a watch loop is the normal exit, not a failure.
        print(flush=True)
        success("👋 Stopped watching.")
        return 0


if __name__ == "__main__":
    run_cli(main)
