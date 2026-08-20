#!/usr/bin/env python3
"""🎬 Show the latest GitHub Actions run for every open PR you authored.

One row per PR, so a repo with five open PRs gets five rows. The repo name is a
terminal hyperlink to that run.

When a PR's head commit has several workflow runs, the row shows the one worth
acting on: anything still in flight, else a failure, else the most recent run.

Usage:
  all-actions.py [--owner=NAME[,NAME...]] [--author=NAME] [--pr-limit=N]
                 [--watch[=SECONDS]] [--interval=SECONDS]

Options:
  --owner=NAME       Owner(s) to scan, comma-separated (default: your gh login)
  --author=NAME      PR author to match (default: your gh login)
  --pr-limit=N       Open PRs to inspect, max 100 (default: 100)
  --interval=SECONDS Refresh interval used by --watch (default: 15)
  --watch[=SECONDS]  Refresh every interval until interrupted
  --help             Show help
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    CYAN,
    GREEN,
    MAGENTA,
    NC,
    RED,
    YELLOW,
    build_parser,
    color_enabled,
    info,
    note,
    require_binary,
    run,
    run_cli,
    run_output,
    success,
    warning,
)

__version__ = "2.0.0"

STATUS_COLORS = {
    "in_progress": CYAN,
    "queued": YELLOW,
    "waiting": YELLOW,
    "pending": YELLOW,
    "requested": YELLOW,
    "success": GREEN,
    "failure": RED,
    "timed_out": RED,
    "startup_failure": RED,
    "action_required": RED,
}

STATUS_ICONS = {
    "in_progress": "🔄",
    "queued": "⏳",
    "waiting": "⏳",
    "pending": "⏳",
    "requested": "⏳",
    "success": "✅",
    "failure": "❌",
    "timed_out": "❌",
    "startup_failure": "❌",
    "cancelled": "🚫",
    "skipped": "⏩",
    "none": "➖",  # noqa: RUF001
}

LIVE_STATUSES = frozenset({"in_progress", "queued", "waiting", "pending", "requested"})
BAD_CONCLUSIONS = frozenset({"FAILURE", "TIMED_OUT", "STARTUP_FAILURE"})

GRAPHQL_QUERY = """
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
            commit {
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
          }
        }
      }
    }
  }
}
"""


# U+FE0F, the emoji presentation selector. It renders the PRECEDING character
# as an emoji, which is two columns wide even when that base character is a
# narrow symbol - so it promotes rather than taking zero width of its own.
# Workflow names like "✔️ Lint" and "⚠️ Nightly" are exactly this shape.
VARIATION_SELECTOR_16 = "\ufe0f"


def display_width(text: str) -> int:
    """Terminal columns ``text`` occupies.

    The shell version counted 4-byte UTF-8 sequences and kept a hand-maintained
    list of double-width BMP emoji, which had to grow every time a new icon was
    added. ``unicodedata`` covers the common cases directly: wide and fullwidth
    characters take two columns, combining marks take none, everything else
    takes one.

    Known limitation, unchanged from the shell version: a ZWJ sequence such as
    "👨‍💻" is counted per component rather than as one glyph, so it over-counts.
    """
    width = 0
    previous = 0

    for char in text:
        if char == VARIATION_SELECTOR_16:
            # Promote a narrow base to two columns; a base that is already
            # wide stays wide.
            if previous == 1:
                width += 1
                previous = 2
            continue
        if unicodedata.combining(char):
            continue
        previous = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        width += previous

    return width


def pad(value: str, width: int) -> str:
    """Left-align ``value`` in a cell ``width`` terminal columns wide."""
    return value + " " * max(0, width - display_width(value))


def pad_link(url: str, value: str, width: int) -> str:
    """Same as :func:`pad`, but wraps the text in an OSC 8 hyperlink.

    The escape sequences are zero-width, so the padding is computed from the
    plain text and only the text itself gets wrapped. Suppressed alongside
    color, so a piped or NO_COLOR run is plain text throughout.
    """
    padding = " " * max(0, width - display_width(value))
    if not url or not color_enabled():
        return value + padding
    return f"\033]8;;{url}\033\\{value}\033]8;;\033\\{padding}"


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


def run_duration(status: str, created: str, updated: str) -> str:
    """How long a run took.

    Completed runs are createdAt -> updatedAt; anything still in flight is
    measured against now, so the column ticks up while it runs.
    """
    start = parse_iso(created)
    if start is None:
        return "-"

    if status in LIVE_STATUSES:
        end = datetime.now(UTC)
    else:
        end = parse_iso(updated)
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


def build_rows(payload: dict) -> list[dict]:
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

        suite = pick_suite(suites)

        if suite is None:
            status = "none"
            workflow = "-"
            created = updated = ""
            url = pr.get("url") or ""
            live = False
        else:
            workflow_run = suite["workflowRun"]
            if suite.get("status") != "COMPLETED":
                # `or "unknown"`: jq died outright on a null status, taking the
                # whole run's output with it. An empty cell would be worse
                # than saying so.
                status = (suite.get("status") or "unknown").lower()
                live = True
            else:
                status = (suite.get("conclusion") or "unknown").lower()
                live = False
            workflow = ((workflow_run.get("workflow") or {}).get("name")) or "-"
            created = workflow_run.get("createdAt") or ""
            updated = workflow_run.get("updatedAt") or ""
            url = workflow_run.get("url") or ""

        rows.append(
            {
                "repo": (pr.get("repository") or {}).get("nameWithOwner") or "",
                "number": pr["number"],
                "branch": pr.get("headRefName") or "",
                "live": live,
                "status": status,
                "workflow": workflow,
                "created": created,
                "updated": updated,
                "url": url,
            }
        )

    return rows


def fetch_rows(owners: str, author: str, pr_limit: int) -> list[dict]:
    """Every open PR and its head-commit check suites, in a single GraphQL call.

    One call keeps a 15-second refresh well inside the rate limit.
    """
    # `user:` qualifiers are OR'd by GitHub search, so several owners widen the
    # sweep rather than narrowing it.
    query = f"is:pr is:open archived:false author:{author}"
    for owner in owners.split(","):
        owner = owner.strip()
        if owner:
            query += f" user:{owner}"

    completed = run(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={GRAPHQL_QUERY}",
            "-f",
            f"q={query}",
            "-F",
            f"first={pr_limit}",
        ],
        check=False,
        capture=True,
    )
    if completed.returncode != 0:
        return []

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return []

    return build_rows(payload)


def render(owners: str, author: str, pr_limit: int) -> None:
    """Draw the table once."""
    single_owner = "," not in owners

    rows = fetch_rows(owners, author, pr_limit)
    # After the fetch, not before: the shell called date(1) inside the banner,
    # so in --watch mode the timestamp reflects when the data landed.
    clock = datetime.now().strftime("%H:%M:%S")

    if not rows:
        note("═══════════════════════════════════════════")
        note(f"🎬  all-actions — {clock}")
        note("═══════════════════════════════════════════")
        info(f"🫙 No open pull requests authored by {author} under: {owners}")
        return

    # In-flight rows first, then grouped by repo, newest run first. Two passes
    # because Python's sort is stable: the second pass preserves the ordering
    # the first established within each group.
    rows.sort(key=lambda r: r["created"] or "", reverse=True)
    rows.sort(key=lambda r: (not r["live"], r["repo"]))

    repo_count = len({r["repo"] for r in rows})

    note("═══════════════════════════════════════════")
    note(f"🎬  all-actions — {len(rows)} open PR(s) · {repo_count} repo(s) · {clock}")
    note("═══════════════════════════════════════════")

    def label(row: dict) -> str:
        return row["repo"].split("/", 1)[-1] if single_owner else row["repo"]

    def status_cell(row: dict) -> str:
        return f"{STATUS_ICONS.get(row['status'], '⚪')} {row['status']}"

    w_repo = max(4, *(display_width(label(r)) for r in rows))
    w_pr = max(3, *(display_width(f"#{r['number']}") for r in rows))
    w_status = max(6, *(display_width(status_cell(r)) for r in rows))
    w_workflow = max(8, *(display_width(r["workflow"]) for r in rows))
    w_branch = max(6, *(display_width(r["branch"]) for r in rows))
    w_age, w_took = 4, 5

    header = "  ".join(
        [
            pad("REPO", w_repo),
            pad("PR", w_pr),
            pad("STATUS", w_status),
            pad("WORKFLOW", w_workflow),
            pad("BRANCH", w_branch),
            pad("AGE", w_age),
            "TOOK",
        ]
    )
    colors = color_enabled()
    print(f"{MAGENTA}{header}{NC}" if colors else header, flush=True)

    live_count = 0
    for row in rows:
        cells = "  ".join(
            [
                pad_link(row["url"], label(row), w_repo),
                pad(f"#{row['number']}", w_pr),
                pad(status_cell(row), w_status),
                pad(row["workflow"], w_workflow),
                pad(row["branch"], w_branch),
                pad(iso_to_age(row["created"]), w_age),
                pad(run_duration(row["status"], row["created"], row["updated"]), w_took),
            ]
        )
        color = STATUS_COLORS.get(row["status"], NC)
        print(f"{color}{cells}{NC}" if colors else cells, flush=True)
        if row["live"]:
            live_count += 1

    idle_count = len(rows) - live_count
    print(flush=True)
    if live_count == 0:
        success(f"😴 Nothing in flight — {idle_count} open PR(s) showing their last run.")
    else:
        success(f"═══ {live_count} in flight · {idle_count} settled (last run) ═══")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="all-actions",
        description=(
            "🎬 Show the latest GitHub Actions run for every open pull request you\n"
            "   authored, across every repo you own - one row per PR, so a repo with\n"
            "   five open PRs gets five rows. The repo name is a terminal hyperlink\n"
            "   to that run.\n\n"
            "   When a PR's head commit has several workflow runs, the row shows the\n"
            "   one worth acting on: anything still in flight, else a failure, else\n"
            "   the most recent run."
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
        dest="pr_limit",
        help="Open PRs to inspect, max 100 (default: 100)",
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

    interval_raw = args.interval
    if args.watch:
        interval_raw = args.watch

    for name, value in (("pr-limit", args.pr_limit), ("interval", interval_raw)):
        if not re.fullmatch(r"[0-9]+", value):
            warning(f"❌ --{name} must be a non-negative integer (got: {value})")
            return 1

    # The GraphQL search connection caps out at 100 nodes per page.
    pr_limit = min(100, max(1, int(args.pr_limit)))
    interval = max(1, int(interval_raw))
    watch = args.watch is not None

    if run(["gh", "auth", "status"], check=False, capture=True).returncode != 0:
        warning("❌ Not logged in to GitHub. Run: gh auth login")
        return 1

    owners = args.owner
    author = args.author
    if not owners or not author:
        login = run_output(["gh", "api", "user", "--jq", ".login"], check=False).strip()
        if not login:
            # Without a login the query loses its `user:` qualifier entirely and
            # silently searches all of GitHub. A token can pass `gh auth status`
            # and still fail here (missing read:user, unauthorised SSO, a 5xx).
            warning("❌ Could not determine your gh login. Pass --owner= and --author=.")
            return 1
        owners = owners or login
        author = author or login

    if not watch:
        render(owners, author, pr_limit)
        return 0

    try:
        while True:
            # ANSI clear + home, rather than shelling out to clear(1).
            print("\033[2J\033[H", end="", flush=True)
            try:
                render(owners, author, pr_limit)
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
