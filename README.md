# Shell Functions

> a collection of helper scripts shared amongst computers, called by name from zsh

The scripts are Python; the thin wrappers that give them their names are zsh
functions. `.zshrc` in this repo is the single source of truth for those
wrappers.

## Getting Started

- pull the latest changes from the main branch
- re-source your `~/.zshrc`
- if the script is new, add its wrapper to your `.zshrc` file

Nothing needs installing to *run* the scripts. They are standard-library-only
Python 3.12+, so a bare `python3` is the entire runtime — no venv, no
`pip install`, no `uv` at call time. The one exception is
`detect-green-magenta-videos`, which needs OpenCV and re-execs itself under a
dedicated venv (it prints the bootstrap command if that venv is missing).

## Layout

```
bin/
  utils.py            shared library: logging, format_bytes, arg parsing,
                      subprocess, file walking, ffprobe
  drives/             mount, eject, and keep-alive for the NAS volumes
  files/              delete/compress/inspect files by extension or size
  git/                branch hygiene, worktrees, GitHub Actions status
  system/             Homebrew updates, btop launcher
  video/              codec inspection, renaming, dedupe, metadata
test/                 pytest suites
.zshrc                the zsh function wrappers (single source of truth)
```

## CLI conventions

Every script follows the same shape, described in full at the top of
`bin/utils.py`:

- **Long flags only**, `--name=value` for values.
- **Booleans** accept a bare `--flag` *and* `--flag=true|false` (plus
  `yes|no`, `1|0`, `on|off`). A bare `--flag` never swallows the next argument.
- **`--help`** on every script.
- **Destructive scripts default to dry-run.** `delete-by-ext`,
  `delete-empty-folders`, `delete-smb-files`, `files-under-size`,
  `fix-codecs`, `delete-duplicate-videos` and `rename-video-file` preview by
  default; the `.zshrc` wrapper sets `DRY_RUN=false` for the real thing, and a
  `-dr` wrapper forces the preview.
- **A symlinked `--path` is refused.** `find` never followed a symlinked start
  point, so pointing a delete tool at `~/media -> /Volumes/...` used to be a
  silent no-op. Pass the real path to act on it.


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

## Running tests

This repo uses [Bun](https://bun.sh) as its task runner and
[uv](https://docs.astral.sh/uv/) to supply the dev tooling.

```sh
bun run test    # pytest
bun run ci      # ruff check + ruff format --check + syntax + exec bits + shebangs + pytest
```

Neither `pytest` nor `ruff` needs to be installed globally: the scripts shell
out to `uv run --with-requirements requirements-dev.txt`, which builds an
ephemeral environment per invocation. Versions are pinned exactly in
`requirements-dev.txt`.

(Note: plain `bun test` invokes Bun's built-in JS/TS test runner, which doesn't
apply here — always use `bun run test`.)

## External tools

The scripts shell out to these where relevant, and fail with an install hint
when one is missing:

| Tool | Used by |
| --- | --- |
| `ffprobe` / `ffmpeg` | `show-codecs`, `fix-codecs`, `find-video-mkv-issues`, `scan-videos-audio-language` |
| `mpv` | `validate-video-files` |
| `exiftool` | `remove-metadata` |
| `gh` | `all-actions` |
| `git` | everything in `bin/git/` |
| `diskutil`, `osascript`, `sfltool` | `bin/drives/` (macOS only) |
| `brew` | `update-brew` |
| `btop` | `btop-launch` |

`zip`, `bc`, `jq`, `perl`, `awk` and `sort` are no longer needed — the standard
library covers what they were doing.

## History

These scripts were bash until August 2026. `git log` has the shell versions;
the migration commit explains each deliberate behavioural change, and anywhere
the Python intentionally differs from the bash it replaced, there is a comment
at that line saying so.
