---
name: sync-all-branches
description: >-
  Use when asked to sync all branches or worktrees in a Git repo: "sync all
  branches", "pull the latest everywhere", "update my worktrees", "sync my
  branches", or "these branches are out of sync". Fetches and prunes remote
  refs, then updates every local branch against its upstream (falling back to
  origin/<branch>). Updates branches checked out in locked worktrees in place,
  preserving directories and locks. Safely stashes/restores unfinished tracked
  and untracked work. Continues independent branches after recoverable failures
  and reports a nonzero partial result. Prunes local branches whose upstream is
  gone once proven merged into the default branch. Never pushes, hard resets,
  deletes unmerged branches or collapses worktrees.
---

# Sync All Branches

## Goal

Bring every local branch and its existing working copy up to date with its remote,
without destroying the user's workspace. A worktree is an active workspace, not a
throwaway directory. A Git worktree lock prevents removal or pruning; it does not
prevent fetching or updating the branch inside that worktree.

## Run

The logic lives in che (`bin/git/sync-all-branches.py`); this skill drives it.

```bash
che sync-all-branches
```

Run once from any working tree in the repo, as a single Bash invocation, so the
user sees the whole transcript. It covers every branch and worktree; they share
refs, so no separate invocation per worktree is needed. Avoid concurrent Git
operations or editing while it runs, especially while unfinished work is
temporarily stashed.

If `che` is not found, che is not installed on this machine: say so and stop
rather than reimplementing the sync by hand.

| Form | Meaning |
|---|---|
| `che sync-all-branches-dr` | Preview from cached remote refs; changes nothing, does not even fetch |
| `--author=EMAIL` | Only track new origin branches by this author (default: all) |
| `--limit=N` | Recent origin refs to inspect for new branches (default: 100) |

Use the `-dr` preview when the user asks to look first. Its view of origin is only
as fresh as the last fetch; do not claim it contacted origin.

## Workflow

1. **Fetch once** (`git fetch --all --prune`). If fetching fails, stop before
   updating any local branch or working copy. Pruning removes obsolete
   remote-tracking refs, not local branches or directories.
2. **Enumerate every local branch**, including the caller's branch, main and
   branches already held by worktrees. Use the configured upstream; if none is
   configured, use `origin/<branch>` when that ref exists. Never infer a target
   for an unrelated local-only branch.
3. **Route occupied branches into their existing worktree** with `git -C <path>`.
   Keep both the directory and lock. An active rebase/bisect can temporarily
   detach HEAD while reserving its branch; it is recognized and left untouched.
4. **Skip branches that already include their upstream.** Ahead-only branches
   keep their local commits and are reported current with origin, not identical.
5. **Update branches needing remote commits:**
   - An unoccupied branch is updated in a disposable worktree; the caller's
     checkout is never switched.
   - A dirty occupied worktree is stashed (tracked and untracked, not ignored)
     with an exact stash object ID, rebased, then restored with
     `git stash apply --index <id>`. Only that stash entry is dropped, and only
     after a clean restore. Unrelated stashes survive.
   - A diverged branch whose changes are all already upstream (`adds_nothing`)
     moves to its upstream with `reset --keep` instead of replaying stale
     pre-squash commits.
   - Dirty submodules and in-progress merges, rebases, cherry-picks, reverts and
     bisects are left untouched and reported.
6. **Continue independent branches after a recoverable failure.** Only the
   rebase this run started is aborted, saved WIP is restored where possible, and
   the run exits nonzero. If aborting its own rebase fails, it stops immediately
   with recovery details.
7. **Track new origin branches** that are not local yet and not merged, with
   `git branch --track`, not checkout.
8. **Preserve the caller's checkout.** Main is updated like any other branch and
   never hard reset. Nothing is pushed.

## Gone upstreams

A deleted remote branch alone is not proof of a merge (a PR can be declined). A
branch whose upstream is gone is deleted, with its clean worktree, only once it is
proven merged into origin's main/master/dev/develop: by ancestry, `adds_nothing`,
a patch-ID squash probe, or a merged GitHub PR. Otherwise it is kept and reported
as `Upstream gone`, which is not a failure. A merged branch whose worktree is
dirty, mid-operation or the caller's checkout is kept as `Merged, kept`. A branch
whose upstream still exists is never pruned.

## Conflicts and recovery

- **Rebase conflict:** the run aborts its rebase in the named worktree and
  restores the WIP. Report the branch as blocked; do not resolve conflicts or
  force-reset to origin.
- **Stash restore conflict:** the branch may already include origin, but its WIP
  needs attention. The recovery stash and working-copy changes are kept; report
  the worktree path and stash ID. Do not drop or blindly reapply the stash.
- **Interrupted run:** report the active worktree and recovery stash. Never pop
  the latest stash automatically; worktrees share one stash ref.
- **Local-only branch, detached worktree, unavailable worktree:** kept and
  reported, never bypassed or pruned.

## Reporting

Relay the summary table: updated, up to date, tracked new, local only, pruned,
upstream gone (with why each was kept), WIP restored and blocked, with branch
names and paths. Give every blocker's reason and recovery stash ID. Say whether
the remaining branches were attempted, that the caller's checkout was preserved
and that nothing was pushed. Never claim every branch synced when the run
returned nonzero.

Ahead/behind arrows measure divergence from upstream. Pulling clears the behind
count but leaves local commits ahead; do not promise both reach zero.

## Safety boundaries

- Never remove existing worktrees, release their locks, hard reset branches or
  push as part of syncing. Never delete a branch by hand to finish the job.
- Never delete untracked files to clear a dirty check.
- Never bypass Git's branch reservation or force a checkout/removal.
- To change the behaviour, change `bin/git/sync-all-branches.py` and
  `bin/branchsync.py` in the che repo and extend `test/test_sync_all_branches.py`.
