# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

A personal collection of Python helper scripts shared across the user's
machines, invoked by name through shell function wrappers. Each script under
`bin/<category>/` is a standalone executable.

`bin/commands.py` is the canonical source of the command surface. The wrappers
under `shell/` are **generated** from it by `bin/install.py`, and `che install`
writes a small block into the user's rc files that sources them. Nothing is
hand-maintained in a `.zshrc` any more; the repo's `.zshrc` is a one-line shim
kept so older setups that source it keep working.

The scripts were bash until August 2026. Nothing in `bin/` is shell any more.

## Architecture

- `bin/che.py` — the dispatcher. `che` with no arguments opens a full-screen
  menu; `che <name> [args]` `exec`s the script with the same environment its
  wrapper would have used; `che install|update|doctor|uninstall|list|
  completions` manage the install itself.
- `bin/commands.py` — the command manifest, and the single source of truth for
  wrappers, completions, the menu and the doctor report. One `Command(...)` per
  user-facing name: script, sound, `dry_run` style (`"env"` for `DRY_RUN=`,
  `"flag"` for `--dry-run`), required binaries, full flag list, and the curated
  questions the menu asks. A `dry_run` value also generates the `-dr` twin.
- `bin/install.py` — installer, first-run wizard, `doctor`, self-`update`,
  `uninstall`. Edits rc files only between its `# >>> che shell functions >>>`
  markers, backs every file up to `~/.config/che/backups/` first, and records
  what it did in `~/.config/che/config.json`. `--replace-legacy` removes the
  hand-written wrappers from before it existed.
- `bin/shellgen.py` — renders `shell/che.{zsh,bash,fish}` and
  `shell/completions/*` from the manifest. Generated files are committed and
  must stay machine-independent; `bun run ci` fails when they are stale.
- `bin/tui.py` — terminal primitives for the menu and the wizard: alternate
  screen and raw mode with guaranteed teardown, key decoding, a flicker-free
  frame buffer, width-aware truncation (emoji are two columns), and readline
  prompts.
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
- `shell/` — GENERATED. Never edit by hand: change `bin/commands.py` and run
  `bun run generate`. Each wrapper invokes its script through `$CHE_PYTHON`,
  then calls `che_notify <sound> $?`, which plays `playsound-N` when that
  exists (it is defined outside this repo) and returns the script's own exit
  status.
- `install.sh` — bootstrap for a bare machine: finds or clones the repo, finds
  a python3 >= 3.12, then hands over to `bin/install.py`.
- `.zshrc` — a generated shim that sources `shell/che.zsh`, kept only so an
  existing `source .../shell-functions/.zshrc` keeps working.
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

- **Shebang**: `#!/usr/bin/env python3`. The libraries at the `bin/` root
  (`utils.py`, `commands.py`, `shellgen.py`, `tui.py`) have no shebang and are
  not executable. `bun run ci` enforces the pairing in both directions: a file
  with a shebang must be executable, an executable file must have a shebang.
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
2. Add a `Command(...)` to `bin/commands.py`: category, summary (under 78
   characters, no trailing period), script path, `playsound-N` number,
   `dry_run` style if it can preview, `needs` for external binaries, the full
   `flags` tuple, and two or three `Prompt`s for the menu. Every prompt flag
   must appear in `flags`; a test enforces it.
3. `bun run generate` to rewrite `shell/`, and commit the result.
4. Keep flag parsing and dry-run semantics consistent with neighbouring scripts.
5. Add or extend a `test/test_*.py` suite for anything with real logic.
6. Run `bun run ci` before committing.

## Git commit messages

- Short and concise.
- Favour bullet points over prose.
- Easy to read at a glance.
- Do **not** add a `Co-Authored-By: Claude Opus` (or any Claude) trailer.
