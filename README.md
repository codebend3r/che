## Shell Functions

> a list of shell functions to share amongst computers

## Getting Started

- pull the latest changes from the main branch
- if the script is new, add it to your `.zshrc` file

## Running tests

This repo uses [Bun](https://bun.sh) as its default package runner.

```sh
bun run test
```

Under the hood the `test` script delegates to `bash test/run-all.sh`, so Bun is only orchestrating — the suites themselves stay pure bash. (Note: plain `bun test` invokes Bun's built-in JS/TS test runner, which doesn't apply here — always use `bun run test`.)
## Syncing branches and worktrees

```sh
sync-all-branches       # push every worktree, collapse the pushed ones, then sync
sync-all-branches-dr    # preview only
update-from-origin      # same, but --no-push: only collapses already-pushed worktrees
```

A worktree is a temporary workspace. Once its commits are on origin the
directory holds nothing the remote doesn't, so `sync-all-branches` pushes it,
removes the directory, and leaves the branch behind as an ordinary local
branch. That also clears the `already used by worktree` pin, which is what
otherwise makes `main` un-checkoutable and stale branches un-deletable.

A worktree is only collapsed when it is **clean** *and* **fully pushed**.
Anything else is kept and reported with the reason.
