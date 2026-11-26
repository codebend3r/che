---
name: sync-all-repos
description: >-
  Use when asked to sync every repo at once: "sync all my repos", "sync all my
  branches everywhere", "update all my projects", "run sync-all-branches on
  everything", "prune and pull across all repos", "morning repo sweep".
  Discovers every git repo under the configured roots and runs
  sync-all-branches in each, caching per-repo results against a fingerprint of
  that repo's local and remote state, so unchanged repos are reported from
  cache instead of re-synced and repeat runs finish in seconds.
---

# Sync All Repos

## Overview

A sweep of `sync-all-branches` across every repo, with a result cache so the sweep
is cheap to repeat. The logic lives in che (`bin/git/sync-all-repos.py`); this skill
drives it.

Per repo:

1. **Gates.** Not a repo or no `origin`: skipped with that reason. Dirty repos are
   synced, not skipped; `sync-all-branches` stashes and restores their work.
2. **Fingerprint.** Local and remote-tracking refs, HEAD, the worktree layout and
   which worktrees are dirty or mid-operation, the remote's branch tips (one
   `git ls-remote`, which downloads no objects), the sync code and the flags passed
   through to it.
3. **Cache lookup.** A fingerprint matching the last successful sync means nothing
   moved: the stored summary is printed as cached and nothing runs.
4. **Sync.** Otherwise `sync-all-branches` runs in the repo and the cache entry is
   rewritten from the *post-sync* state.

Repos run 4 at a time by default, with output in discovery order.

**Caching is the point, so never bypass it casually.** `--force` is for when the
cache is suspect, not a default.

## Running it

```bash
che sync-all-repos
```

Run it once, as a single Bash invocation, so the user sees the whole transcript.
If the user wants a preview first, run `che sync-all-repos-dr`, which reports
cached / would sync / skipped per repo and syncs nothing.

If `che` is not found, che is not installed on this machine: say so and stop
rather than looping `sync-all-branches` by hand.

| Flag | Meaning |
|---|---|
| `--root=PATH` | Root to scan; repeatable (default `~/Developer/git`, or `$SYNC_ALL_REPOS_ROOTS`, colon separated) |
| `--depth=N` | Levels below each root to scan (default 2) |
| `--jobs=N` | Repos processed at once (default 4) |
| `--force` | Ignore cached results, sync everything, refresh the cache |
| `--offline` | Skip the remote probe; fingerprint local state only. A push made elsewhere goes unnoticed |
| `--summary-only` | For synced repos print only the summary table. Failures print in full |
| `--stop-on-error` | Start no more repos after the first failure |
| `--clear-cache` | Delete the cache and exit |
| `--cache-dir=PATH` | Cache location (default `~/.cache/che/sync-all-repos`) |
| `--timeout=N` | Per-repo sync timeout in seconds (default 300, `0` disables) |
| `--author=EMAIL`, `--limit=N` | Passed to `sync-all-branches` and folded into the cache key |

Positional arguments restrict the sweep to specific repos:

```bash
che sync-all-repos ~/Developer/git/pokemax ~/Developer/git/kasane
```

Exit codes: `0` everything synced or cached, `1` at least one repo failed, `2`
nothing failed but something was skipped.

## What gets discovered

Directories containing a `.git` **directory**, up to `--depth` levels below each
root.

- **Secondary worktrees are not repos here.** Their `.git` is a file, and their
  branches are synced from the main clone.
- **Nested repos are skipped.** A submodule or vendored clone is the outer repo's
  business.
- `node_modules`, `vendor`, `.venv`, `.build`, `Library` and `.Trash` are pruned.

## Behaviour notes

- **The sweep is not atomic.** One failing repo does not stop the rest; use
  `--stop-on-error` for that.
- **Only successful syncs are cached.** Failures and skips write no entry, so the
  next run retries them.
- **`--offline` and online runs keep separate fingerprints** and do not invalidate
  each other; the next online run re-syncs anything only an offline run has seen.
- **An unreachable remote is a skip,** not a sync whose fetch would fail anyway.
- **Nothing is pushed**, here or in `sync-all-branches`.

## Reporting back

Lead with the split: how many repos were **synced**, **cached**, **skipped** and
**failed**. Name the cached ones; that is why the run was cheap. Their stored
summary is the last known state, so describe it as such, not as work done now.

For each synced repo, report what `sync-all-branches` reported (updated, pruned,
upstream gone, tracked new, blocked) rather than just "synced". Call out each skip
with its reason. For a failure, say which branch failed at which step, and that
the sweep carried on. Do not resolve rebase conflicts.

## Red flags

- Reaching for `--force` because a result looks stale: find out which fingerprint
  input changed instead. Silent staleness is a cache bug worth fixing.
- Every repo reports `unreachable`: the network or credentials are down. Stop and
  say so; rerunning will not help.
- Every repo misses the cache right after a successful run: something in the
  fingerprint is unstable. Investigate before trusting the cache.
- Tempted to hand-run `sync-all-branches` in each repo in a loop: that is this
  command minus the cache, the skip handling and the failure reporting.
- Asked to "sync and push everywhere": neither command ever pushes; ask first.
