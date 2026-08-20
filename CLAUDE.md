# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

A personal collection of Python helper scripts shared across the user's
machines, invoked by name through zsh function wrappers. Each script under
`bin/` is a standalone executable. The repo's `.zshrc` is the canonical source
of the wrappers the user sources from their home `~/.zshrc`.

The scripts were bash until August 2026. Nothing in `bin/` is shell any more.

## Architecture

- `bin/<category>/*.py` — scripts grouped by purpose. Categories: `git/`,
  `video/`, `files/`, `drives/`, `system/`. Each script parses its own CLI flags.
- `bin/utils.py` — shared library at the `bin/` root, imported by every script
  via:
  ```python
  sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

  from utils import build_parser, info, iter_files, run_cli, scan_root, warning
  ```
  It provides color logging (`log`, `warning`, `info`, `note`, `success`),
  `format_bytes`, `parse_size`, the arg-parsing helpers (`build_parser`,
  `add_bool_flag`, `env_bool`), subprocess wrappers (`run`, `run_output`,
  `run_lines`, `run_cli`, `require_binary`), worktree/branch helpers
  (`worktree_paths`, `main_worktree`, `worktree_branch_map`,
  `worktree_for_branch`, `worktree_is_clean`, `branch_is_pushed`,
  `find_main_branch`), file walking (`iter_files`, `scan_root`,
  `normalize_extensions`) and ffprobe helpers. Its module docstring is the
  authoritative statement of the CLI conventions.
- `.zshrc` — thin wrappers that `python3`-invoke each script (via
  `${SHELL_FUNCTIONS_BIN}/<category>/<script>.py`) and then call a
  `playsound-N` notification (defined outside this repo). When adding a new
  script, add a wrapper here too. The `.zshrc` header marks this repo as the
  **single source of truth** for these wrappers.
- `bin/version-bump.py` — vestigial (uses `npm`/`pnpm`); does not apply to this
  repo and shouldn't be invoked here.

## Worktrees

A branch checked out in a linked worktree cannot be checked out, deleted or
reset from the main clone — git refuses with `already used by worktree`. That
is a mechanical limit, not a conflict, so anything in `bin/git/` that touches
branches asks `worktree_branch_map()` which ones are pinned and where, then
works around the pin rather than counting it as a failure:

- `clean-stale-branches` reports pinned stale branches and deletes the rest.
- `update-local-branches` rebases a pinned branch in place with `git -C <wt>`.
- `sync-all-branches` pushes each worktree, collapses the clean + fully pushed
  ones back into plain local branches, then delegates to the three scripts
  above. Only clean **and** pushed worktrees are collapsed; anything else is
  kept and reported with the reason. It releases a worktree lock before
  removal, never `--force` (which discards real work).

## Conventions for scripts in `bin/<category>/`

- **Shebang**: `#!/usr/bin/env python3`. `bin/utils.py` is a library — no
  shebang, not executable. The `bun run ci` checks enforce both.
- **Standard library only.** These run from a bare `python3` on every machine
  the repo is cloned to; a third-party import would mean a venv at call time.
  The sole exception is `detect-green-magenta-videos.py`, which needs OpenCV
  and re-execs itself under `$DETECT_GM_PYTHON`.
- **Import utils** via the `sys.path.insert` pattern above so the script works
  regardless of CWD.
- **CLI flag style**: long flags with `=` for values (`--path=/foo`,
  `--recursive`, `--dry-run`, `--ignore-words=A,B`). Build the parser with
  `build_parser` and booleans with `add_bool_flag`, which gives both `--flag`
  and `--flag=value` without letting a bare flag swallow the next argument.
  Use `allow_value=False` for inverted flags like `--no-force`.
- **Dry-run default**: destructive scripts default `DRY_RUN=true` via
  `env_bool("DRY_RUN", True)`. The `.zshrc` wrapper flips it to `false` and
  exposes a separate `-dr` wrapper for the preview. Match this for new
  destructive scripts.
- **Version marker**: scripts carry `__version__ = "2.1.0"`. Bump it when
  meaningfully changing behaviour.
- **Logging**: use the helpers from `utils.py` rather than bare `print` for
  status output, so colors stay consistent and `NO_COLOR` is honoured.
- **Exit handling**: end with `run_cli(main)` so exit codes, `CalledProcessError`
  reporting and Ctrl-C are identical across the repo.
- **File iteration**: use `iter_files()`. It streams like `find` (constant
  memory, output as it goes), reproduces `-iname '*.ext'` including glob
  patterns and dot-only names, skips symlinks and `._*` sidecars, and raises on
  a missing root. Validate a user-supplied root with `scan_root()`, which also
  refuses a symlinked start point.

## Documenting divergence

Every place the Python intentionally behaves differently from the bash it
replaced carries a comment at that line saying so and why. Keep that up: a
divergence without a comment is indistinguishable from a porting bug, and the
review pass that produced this migration found several of each.

## External tool dependencies

Video scripts rely on `ffprobe`/`ffmpeg`; `validate-video-files` needs `mpv`,
`remove-metadata` needs `exiftool`, `all-actions` needs `gh`. Use
`require_binary()` for any external binary, with an install hint.

`zip`, `bc`, `jq`, `perl`, `awk` and `sort` were dropped in the migration —
`zipfile`, integer maths, `json`, `re`, and `sorted()` cover them.

## When adding or modifying a script

1. Create the script under the appropriate `bin/<category>/` and `chmod +x` it.
2. If it's new, add a wrapper function to `.zshrc` (with an appropriate
   `playsound-N` call) so it can be invoked by name after re-sourcing.
3. Keep flag parsing and dry-run semantics consistent with neighbouring scripts.
4. Add or extend a `test/test_*.py` suite for anything with real logic.
5. Run `bun run ci` before committing.

## Git commit messages

- Short and concise.
- Favour bullet points over prose.
- Easy to read at a glance.
- Do **not** add a `Co-Authored-By: Claude Opus` (or any Claude) trailer.
