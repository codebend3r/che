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
- `bin/art.py`: the block-letter wordmark, Che's face as 32x18 text, and the
  `banner()` that lays them side by side (falling back to the wordmark alone
  on a narrow terminal). `print_logo`, the menu header and the README's
  `che:banner` island all draw from it.
- `bin/<category>/*.py` — scripts grouped by purpose. Categories: `git/`,
  `video/`, `files/`, `drives/`, `system/`. Each script parses its own CLI flags.
- `bin/utils.py` — shared library at the `bin/` root, imported by every script
  via:
  ```python
  sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

  from utils import build_parser, info, iter_files, run_cli, scan_root, warning
  ```
  It provides color logging (`log`, `warning`, `info`, `note`, `success`,
  `paint`), the fixed banners (`heading`, `note_settings`, `footer_rule`,
  `dry_run_complete`), `format_bytes`, `parse_size`, the arg-parsing helpers
  (`build_parser`, `add_bool_flag`, `env_bool`, `parse_count`), subprocess
  wrappers (`run`, `run_output`, `run_cli`, `require_binary`), file walking and
  removal (`iter_files`, `scan_root`, `normalize_extensions`,
  `report_walk_error`, `remove_or_warn`) and `atomic_write_text`. The
  validators (`scan_root`, `parse_count`, `env_bool`, `require_binary`) report
  and exit 1 themselves. Its module docstring is the authoritative statement
  of the CLI conventions.
- Domain libraries beside it, imported the same way by the scripts that need
  them:
  - `bin/gitutils.py` — `skip_git_hooks`, `fetch_remotes`, `current_branch`,
    `for_each_ref`, `local_branches`, `has_tracked_changes`,
    `worktrees`/`Worktree`, `worktree_branch_map`, `worktree_is_clean`,
    `find_main_branch`, `park_main_worktree`.
  - `bin/media.py` — `probe_media()`, one ffprobe JSON call per file read
    through `MediaProbe`'s accessors, and the shared video extension lists.
  - `bin/nas.py` — the NAS drive table (`NasDrive`) and SMB helpers:
    `select_drives` (`--only`), `warn_unknown_drive`, `is_mounted`, `smb_url`,
    `mount_smb`.
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
- `sync-all-branches` parks the main clone on main (`park_main_worktree()`),
  fetches once (`fetch_remotes()`, whose marker the delegated scripts
  inherit, so none of them fetches again), then delegates to
  `clean-stale-branches`, `update-local-branches` and
  `checkout-my-branches`, which creates tracking
  branches without switching to them, so the run ends on main. It only
  updates branches: it never pushes and never adds, removes or prunes a
  worktree. `--no-push` and `--keep-locked` are still accepted, and ignored,
  because chip passes `--no-push`.
- Every script in `bin/git/` that touches branches (these four plus
  `prune-worktrees`) calls `skip_git_hooks()` first, so no repo hook
  (lefthook, husky) runs on their checkouts and rebases. A new script in
  `bin/git/` that checks out, rebases or commits should call it too.

## Conventions for scripts in `bin/<category>/`

- **Shebang**: `#!/usr/bin/env python3`. The libraries at the `bin/` root
  (`utils.py`, `commands.py`, `shellgen.py`, `tui.py`, `art.py`) have no
  shebang and are not executable. `bun run ci` enforces the pairing in both
  directions: a file with a shebang must be executable, an executable file
  must have a shebang.
- **Standard library only.** These run from a bare `python3` on every machine
  the repo is cloned to; a third-party import would mean a venv at call time.
  The sole exception is `detect-green-magenta-videos.py`, which needs OpenCV
  and re-execs itself under `$DETECT_GM_PYTHON`. It still imports `utils`, which
  loads under that venv too.
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

## Releasing

The repo is published to npm as `@codebend3r/che`; the `bin` entry points
straight at `bin/che.py`, so `npm install -g` puts a `che` on PATH that runs
the dispatcher under whatever `python3` comes first (the dispatcher tolerates
an old one and hands the scripts a new enough interpreter itself).

`package.json` holds the version. `bin/commands.py` reads `VERSION` and
`PACKAGE_NAME` from it, so a release is:

1. `npm version <major|minor|patch>` on `main`. Its `version` hook runs
   `bun run generate` and stages `shell/`, `.zshrc` and the README islands into
   the version commit, so the generated headers never lag the package.
2. `git push --follow-tags`.
3. `npm publish`. `prepublishOnly` runs `bun run ci` first.

The tarball is `bin/` (minus `version-bump.py`) and `shell/` plus the README
and LICENSE; `npm pack --dry-run` lists it. `che update` refuses to run in a
copy without `.git` and prints the npm command instead.

## Git commit messages

- Short and concise.
- Favour bullet points over prose.
- Easy to read at a glance.
- Do **not** add a `Co-Authored-By: Claude Opus` (or any Claude) trailer.
