#!/usr/bin/env python3
"""🗂️ Run sync-all-branches in every repo, skipping the ones that have not moved.

Find every git repo under the configured roots (or take the repos given as
arguments) and run sync-all-branches in each, a few at a time. Each repo's
result is cached against a fingerprint of everything that could change what a
sync would do: local and remote-tracking refs, HEAD, the worktree layout and
which worktrees hold changes, the remote's branch tips (one ``git ls-remote``,
which downloads no objects), the sync code itself and the flags passed through
to it. A repo whose fingerprint matches its last successful sync is reported
from cache and nothing runs, so a repeat sweep costs one ls-remote per repo.
Nothing is pushed.

Usage:
  sync-all-repos.py [options] [REPO ...]

Options:
  --root=PATH       Root to scan for repos; repeatable (default: ~/Developer/git,
                    or $SYNC_ALL_REPOS_ROOTS, colon separated)
  --depth=N         Levels below each root to scan (default: 2)
  --jobs=N          Repos processed at once (default: 4)
  --force           Ignore cached results; sync every repo and refresh the cache
  --offline         Skip the remote probe; fingerprint local state only
  --dry-run         Report cached / would sync / skipped per repo; sync nothing
  --summary-only    For synced repos print only sync-all-branches' summary table
  --stop-on-error   Stop starting new repos after the first failure
  --clear-cache     Delete the cache and exit
  --cache-dir=PATH  Cache location (default: ~/.cache/che/sync-all-repos)
  --timeout=N       Per-repo sync timeout in seconds (default: 300, 0 disables)
  --author=EMAIL    Passed to sync-all-branches (part of the cache key)
  --limit=N         Passed to sync-all-branches (part of the cache key)

Env:
  DRY_RUN=true      Same as --dry-run (used by the shell -dr wrapper)

Exit codes:
  0  every repo synced or served from cache
  1  at least one repo failed to sync
  2  nothing failed, but some repos were skipped (no origin, unreachable)

Ported from the sync-all-repos Claude skill. Where it behaves differently, the
line that does so says why.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitutils import has_changes, in_progress
from report import FAIL, OK, PLAN, SAME, WARN, Listing, Outcome, Tally, duration, plural
from utils import (
    add_bool_flag,
    atomic_write_text,
    build_parser,
    env_bool,
    heading,
    info,
    log,
    note_settings,
    parse_count,
    require_binary,
    run,
    run_cli,
    warning,
)

__version__ = "1.0.0"

BIN = Path(__file__).resolve().parent.parent
SYNC_SCRIPT = BIN / "git" / "sync-all-branches.py"
# Everything a sync's behaviour depends on. An edit to any of them can change
# what a sync would do, so it invalidates every cached result.
SYNC_CODE = (
    SYNC_SCRIPT,
    BIN / "branchsync.py",
    BIN / "gitutils.py",
    BIN / "report.py",
    BIN / "utils.py",
    BIN / "tui.py",
)

# Bump when the fingerprint's inputs or the cache entry's shape change.
CACHE_VERSION = 1
PROBE_TIMEOUT = 25
DEFAULT_TIMEOUT = 300
# A terminated sync gets this long to finish its own cleanup before it is killed.
TERMINATE_GRACE = 10
DEFAULT_ROOT = "~/Developer/git"
ROOTS_ENV = "SYNC_ALL_REPOS_ROOTS"
# Never descended into: dependency trees and system folders hold no repos of ours.
PRUNED = frozenset({"node_modules", "vendor", ".venv", ".build", "Library", ".Trash"})
# sync-all-branches closes with this rule and then its summary table.
_FOOTER_RULE = "─" * 45
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class Result(Outcome):
    SYNCED = (OK, "synced", "Synced", Listing.LIST)
    CACHED = (SAME, "cached", "From cache", Listing.LIST)
    WOULD_SYNC = (PLAN, "would sync", "Would sync", Listing.LIST)
    NOT_VISITED = (SAME, "", "Not visited", Listing.LIST)
    NOT_A_REPO = (WARN, "skipped", "Not a repo", Listing.ALL)
    NO_ORIGIN = (WARN, "skipped", "No origin", Listing.ALL)
    UNREACHABLE = (WARN, "unreachable", "Unreachable", Listing.ALL)
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


SKIPPED = (Result.NOT_A_REPO, Result.NO_ORIGIN, Result.UNREACHABLE)
# Reported with their reason kept in the summary listing, not just shown live.
FLAGGED = (*SKIPPED, Result.FAILED)


@dataclass(frozen=True)
class Settings:
    cache_dir: Path
    code_hash: str
    passthrough: tuple[str, ...]
    force: bool
    offline: bool
    dry_run: bool
    timeout: int
    summary_only: bool


@dataclass(frozen=True)
class RepoResult:
    outcome: Result
    detail: str = ""
    body: str = ""  # printed under the repo's line, indented


# -- discovery ---------------------------------------------------------------


def add_repo(repos: list[Path], path: Path) -> None:
    """Append ``path`` unless it is already listed or sits inside a listed repo.

    A repo inside another (a submodule, a vendored clone) is the outer repo's
    business, so it is never synced on its own.
    """
    for existing in repos:
        if path == existing or path.is_relative_to(existing):
            return
    repos.append(path)


def discover(roots: list[Path], depth: int) -> list[Path]:
    """Every directory holding a ``.git`` directory, at most ``depth`` levels below a root.

    A ``.git`` file marks a linked worktree, whose branches are synced from
    its main clone, so it is not a repo to visit. Neither is anything below a
    repo. Results are sorted per root, so output order is stable.
    """
    repos: list[Path] = []
    for root in roots:
        if not root.is_dir():
            warning(f"⚠️  Skipping missing root: {root}")
            continue
        for current, dirs, _files in os.walk(root):
            here = Path(current)
            dot_git = here / ".git"
            if dot_git.is_dir() and not dot_git.is_symlink():
                add_repo(repos, here)
                dirs[:] = []
                continue
            if dot_git.exists() or len(here.relative_to(root).parts) >= depth:
                dirs[:] = []
                continue
            dirs[:] = sorted(name for name in dirs if name not in PRUNED)
    return repos


def explicit_repos(raw: list[str]) -> list[Path]:
    repos: list[Path] = []
    for arg in raw:
        path = Path(arg).expanduser()
        if not path.is_dir():
            warning(f"❌ No such directory: {arg}")
            sys.exit(1)
        top = git(path, "rev-parse", "--show-toplevel")
        add_repo(repos, Path(top.stdout.strip()) if top.returncode == 0 else path.resolve())
    return repos


def roots_from(raw: list[str]) -> list[Path]:
    if not raw:
        raw = [p for p in os.environ.get(ROOTS_ENV, "").split(":") if p] or [DEFAULT_ROOT]
    return [Path(root).expanduser() for root in raw]


# -- fingerprint -------------------------------------------------------------


def git(repo: Path, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args], check=False, capture=True, timeout=timeout)


def code_hash() -> str:
    combined = hashlib.sha256()
    for path in SYNC_CODE:
        combined.update(path.read_bytes())
    return combined.hexdigest()


def worktree_state(repo: Path) -> list[str]:
    """The porcelain worktree listing, then one line per worktree: whether it
    holds changes and whether an operation is in progress there.

    DELIBERATE DIVERGENCE: the skill skipped a dirty repo outright, because the
    bash sync it drove refused to run on one. sync-all-branches stashes and
    restores that work itself, so a dirty repo is synced here like any other.
    Whether a worktree is dirty still changes what a sync does (a merged branch
    with local changes is kept rather than deleted), so it is part of the key.
    Only whether it is dirty, not what changed, or every edit would miss.
    """
    listing = git(repo, "worktree", "list", "--porcelain", "-z").stdout
    lines = [listing]
    for record in listing.split("\0"):
        if not record.startswith("worktree "):
            continue
        path = Path(record.removeprefix("worktree "))
        if not path.is_dir():
            lines.append(f"tree {path} missing")
            continue
        try:
            lines.append(f"tree {path} dirty={has_changes(path)} busy={in_progress(path)}")
        except (subprocess.CalledProcessError, OSError):
            lines.append(f"tree {path} unreadable")
    return lines


def local_state(repo: Path, settings: Settings) -> str:
    head = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if not head:
        head = "detached " + git(repo, "rev-parse", "HEAD").stdout.strip()
    refs = git(
        repo,
        "for-each-ref",
        "--format=%(refname) %(objectname) %(upstream) %(upstream:track)",
        "refs/heads",
        "refs/remotes",
    ).stdout
    return "\n".join(
        [
            f"cache-version:{CACHE_VERSION}",
            f"passthrough:{' '.join(settings.passthrough)}",
            f"code:{settings.code_hash}",
            f"head:{head}",
            refs,
            *worktree_state(repo),
        ]
    )


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()


class Fingerprint(NamedTuple):
    """A repo's state as hashes: ``local`` alone, and ``full``, which adds the
    remote's branch tips and is None when the remote was not probed (--offline).

    The two modes verify different amounts, so each compares its own: an
    offline run only ``local``, a normal run ``full``. Keeping them apart stops
    one mode invalidating the other's cache entries, and an entry an offline
    run wrote has no ``full``, so the next online run re-syncs.
    """

    local: str
    full: str | None

    def matches(self, entry: dict, offline: bool) -> bool:
        if offline:
            return entry.get("fingerprint_local") == self.local
        return self.full is not None and entry.get("fingerprint") == self.full


def fingerprint(repo: Path, settings: Settings) -> Fingerprint | None:
    """The repo's :class:`Fingerprint`, or None when the remote could not be read."""
    state = local_state(repo, settings)
    if settings.offline:
        return Fingerprint(digest(state), None)
    try:
        probe = git(repo, "ls-remote", "--symref", "--heads", "origin", timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
    if probe.returncode != 0:
        return None
    return Fingerprint(digest(state), digest(f"{state}\nremote:\n{probe.stdout}"))


# -- cache -------------------------------------------------------------------


def entry_path(cache_dir: Path, repo: Path) -> Path:
    name = re.sub(r"[^A-Za-z0-9._-]", "-", repo.name)
    return cache_dir / f"{name}.{digest(str(repo))[:10]}.json"


def read_entry(path: Path) -> dict | None:
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or entry.get("version") != CACHE_VERSION:
        return None
    return entry


def write_entry(path: Path, repo: Path, prints: Fingerprint, summary: str) -> None:
    """Record a successful sync. Only successes are written, so an entry's
    presence is its status. Atomic, so a sweep killed midway leaves the old
    entry or the new one, never half of one.
    """
    entry = {
        "version": CACHE_VERSION,
        "repo": str(repo),
        "fingerprint": prints.full,
        "fingerprint_local": prints.local,
        "synced_at": int(time.time()),
        "summary": summary,
    }
    atomic_write_text(path, json.dumps(entry, indent=2) + "\n")


def ago(epoch: int, now: float | None = None) -> str:
    seconds = max(0, int((time.time() if now is None else now) - epoch))
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    if seconds < 172800:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def summary_block(transcript: str) -> str:
    """sync-all-branches' closing table: everything after its last footer rule."""
    lines = transcript.rstrip("\n").splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip() == _FOOTER_RULE:
            return "\n".join(lines[index + 1 :]).strip("\n")
    return "\n".join(lines[-5:])


# -- per repo ----------------------------------------------------------------


def run_sync(repo: Path, settings: Settings) -> tuple[int | None, str]:
    """Run sync-all-branches in ``repo``; ``(exit code or None on timeout, transcript)``."""
    env = {**os.environ, "NO_COLOR": "1", "DRY_RUN": "false"}
    env.pop("FORCE_COLOR", None)
    # stdin is closed so nothing the sync runs can wait on a prompt that no
    # one will see behind a captured pipe.
    proc = subprocess.Popen(  # noqa: S603 - argv list, shell=False
        [sys.executable, str(SYNC_SCRIPT), *settings.passthrough],
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    try:
        out, _ = proc.communicate(timeout=settings.timeout or None)
        return proc.returncode, out or ""
    except subprocess.TimeoutExpired:
        # DELIBERATE DIVERGENCE: the skill's `timeout` killed the sync
        # outright. SIGTERM first, with a grace period, gives a sync stopped
        # mid-rebase the chance to abort it rather than leave it half done.
        proc.send_signal(signal.SIGTERM)
        try:
            out, _ = proc.communicate(timeout=TERMINATE_GRACE)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        return None, out or ""


def process(repo: Path, settings: Settings) -> RepoResult:
    """Everything for one repo. Runs on a worker thread, so it prints nothing."""
    # Cheap local gates first, before any network round trip.
    if git(repo, "rev-parse", "--git-dir").returncode != 0:
        return RepoResult(Result.NOT_A_REPO, "not a git repository")
    if git(repo, "remote", "get-url", "origin").returncode != 0:
        return RepoResult(Result.NO_ORIGIN, "no origin remote to sync against")
    # DELIBERATE DIVERGENCE: the skill also skipped a detached HEAD. The bash
    # sync needed a branch to return to; sync-all-branches keeps a detached
    # caller checkout where it is and updates every branch around it.

    prints = fingerprint(repo, settings)
    if prints is None:
        return RepoResult(Result.UNREACHABLE, "could not read origin (offline, or auth?)")

    path = entry_path(settings.cache_dir, repo)
    entry = None if settings.force else read_entry(path)
    if entry and prints.matches(entry, settings.offline):
        synced_at = int(entry.get("synced_at", 0))
        when = datetime.fromtimestamp(synced_at).strftime("%Y-%m-%d %H:%M")
        scope = "local state unchanged, remote not checked" if settings.offline else "unchanged"
        return RepoResult(
            Result.CACHED,
            f"{scope}; last synced {when} ({ago(synced_at)})",
            str(entry.get("summary", "")),
        )

    if settings.dry_run:
        reason = "state changed since the last sync" if path.exists() else "no cache entry yet"
        return RepoResult(Result.WOULD_SYNC, reason)

    code, transcript = run_sync(repo, settings)
    transcript = _ANSI.sub("", transcript)
    if code != 0:
        why = f"timed out after {settings.timeout}s" if code is None else f"exit {code}"
        return RepoResult(Result.FAILED, why, transcript)

    summary = summary_block(transcript)
    body = summary if settings.summary_only else transcript
    # The entry is written from the state the sync left behind, so the next
    # run compares against that, not against where this run found the repo.
    after = fingerprint(repo, settings)
    if after is None:
        return RepoResult(Result.SYNCED, "remote went unreachable after the sync; not cached", body)
    write_entry(path, repo, after, summary)
    return RepoResult(Result.SYNCED, "", body)


# -- main --------------------------------------------------------------------


def clear_cache(cache_dir: Path, dry_run: bool) -> int:
    if not cache_dir.exists():
        info(f"No cache to clear at {cache_dir}")
    elif dry_run:
        info(f"Would clear the cache at {cache_dir}")
    else:
        shutil.rmtree(cache_dir)
        log(f"🧹 Cleared the cache at {cache_dir}")
    return 0


def report(tally: Tally[Result], repo: Path, result: RepoResult) -> None:
    name = repo.name
    if result.outcome in FLAGGED:
        tally.flag(result.outcome, name, result.detail)
    else:
        tally.record(result.outcome, name, result.detail)
    if result.body.strip():
        print(textwrap.indent(result.body.rstrip("\n"), "      "), flush=True)


def sweep(
    repos: list[Path], settings: Settings, jobs: int, stop_on_error: bool
) -> tuple[Tally[Result], bool]:
    """Process every repo ``jobs`` at a time, reporting each in discovery order."""
    tally: Tally[Result] = Tally(Result)
    aborted = False
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures: list[Future[RepoResult]] = [pool.submit(process, repo, settings) for repo in repos]
        try:
            with tally.progress(len(repos)) as progress:
                for repo, future in zip(repos, futures, strict=True):
                    if aborted and future.cancel():
                        tally.record(Result.NOT_VISITED, repo.name)
                        continue
                    progress.step(repo.name)
                    try:
                        result = future.result()
                    except (subprocess.SubprocessError, OSError, ValueError) as exc:
                        result = RepoResult(Result.FAILED, f"{type(exc).__name__}: {exc}")
                    report(tally, repo, result)
                    if result.outcome is Result.FAILED and stop_on_error and not aborted:
                        aborted = True
                        warning(f"⛔ --stop-on-error: starting no more repos after {repo.name}")
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
    return tally, aborted


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="sync-all-repos",
        description="🗂️ Run sync-all-branches in every repo, skipping the ones that have not moved.",
    )
    parser.add_argument(
        "repos", nargs="*", metavar="REPO", help="Only these repos (default: scan the roots)"
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        metavar="PATH",
        help=f"Root to scan; repeatable (default: {DEFAULT_ROOT}, or ${ROOTS_ENV})",
    )
    parser.add_argument(
        "--depth", default="2", metavar="N", help="Levels below each root (default: 2)"
    )
    parser.add_argument(
        "--jobs", default="4", metavar="N", help="Repos processed at once (default: 4)"
    )
    add_bool_flag(parser, "--force", help="Ignore cached results and sync every repo")
    add_bool_flag(parser, "--offline", help="Skip the remote probe; fingerprint local state only")
    add_bool_flag(
        parser,
        "--dry-run",
        default=env_bool("DRY_RUN", False),
        help="Report cached / would sync / skipped per repo; sync nothing",
    )
    add_bool_flag(parser, "--summary-only", help="For synced repos print only the summary table")
    add_bool_flag(parser, "--stop-on-error", help="Start no more repos after the first failure")
    add_bool_flag(parser, "--clear-cache", help="Delete the cache and exit")
    parser.add_argument(
        "--cache-dir",
        default="",
        metavar="PATH",
        help="Cache location (default: ~/.cache/che/sync-all-repos)",
    )
    parser.add_argument(
        "--timeout",
        default=str(DEFAULT_TIMEOUT),
        metavar="N",
        help=f"Per-repo sync timeout in seconds (default: {DEFAULT_TIMEOUT}, 0 disables)",
    )
    # DELIBERATE DIVERGENCE: the skill also passed --keep-worktrees through.
    # sync-all-branches never removes a worktree it was not asked to, so it
    # has no such flag. And the skill's --sync-script= is gone: this always
    # drives the sync-all-branches beside it.
    parser.add_argument("--author", default="", metavar="EMAIL", help="Passed to sync-all-branches")
    parser.add_argument("--limit", default="", metavar="N", help="Passed to sync-all-branches")
    args = parser.parse_args(argv)

    depth = max(1, parse_count(args.depth, "--depth"))
    jobs = max(1, parse_count(args.jobs, "--jobs"))
    timeout = parse_count(args.timeout, "--timeout")
    if args.limit:
        parse_count(args.limit, "--limit", minimum=1)
    xdg = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    cache_dir = (
        Path(args.cache_dir).expanduser()
        if args.cache_dir
        else Path(xdg) / "che" / "sync-all-repos"
    )

    if args.clear_cache:
        return clear_cache(cache_dir, args.dry_run)

    require_binary("git")
    # Never let a sync on a worker thread block on a credential prompt.
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    started = time.monotonic()

    repos = explicit_repos(args.repos) if args.repos else discover(roots_from(args.root), depth)
    if not repos:
        warning("❌ No git repositories found.")
        return 1

    passthrough = tuple(
        f"{flag}={value}"
        for flag, value in (("--author", args.author), ("--limit", args.limit))
        if value
    )
    settings = Settings(
        cache_dir=cache_dir,
        code_hash=code_hash(),
        passthrough=passthrough,
        force=args.force,
        offline=args.offline,
        dry_run=args.dry_run,
        timeout=timeout,
        summary_only=args.summary_only,
    )

    heading("🗂️  sync-all-repos", dry_run=args.dry_run)
    note_settings(
        ("Repos", len(repos)),
        ("Jobs", jobs),
        ("Cache", f"{cache_dir}{'  (bypassed: --force)' if args.force else ''}"),
        ("Probe", "local state only (--offline)" if args.offline else "local state + ls-remote"),
    )

    tally, aborted = sweep(repos, settings, jobs, args.stop_on_error)

    notes = []
    if tally.count(Result.CACHED):
        notes.append("From cache: nothing moved since the last sync, so nothing ran there.")
    if tally.count(Result.UNREACHABLE) == len(repos):
        notes.append("Every remote was unreachable: the network or credentials are down.")
    if aborted:
        notes.append("Stopped early (--stop-on-error); repos already running were finished.")
    notes.append(
        "Nothing pushed." if not args.dry_run else "Dry run: nothing synced, cache untouched."
    )
    tally.summary(
        "Preview" if args.dry_run else "Summary",
        facts=[plural(len(repos), "repo"), duration(time.monotonic() - started)],
        notes=notes,
    )
    print()
    if tally.count(Result.FAILED):
        warning(
            f"⚠️  {plural(tally.count(Result.FAILED), 'repo')} failed; the rest were still swept."
        )
        return 1
    if tally.count(*SKIPPED):
        warning(f"⚠️  {plural(tally.count(*SKIPPED), 'repo')} skipped.")
        return 2
    log("🎉 Preview complete." if args.dry_run else "🎉 Sweep complete.")
    return 0


if __name__ == "__main__":
    run_cli(main)
