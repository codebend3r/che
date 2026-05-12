# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

A personal collection of zsh/bash helper scripts shared across the user's machines. There is no build, test, or lint tooling — each script in `bin/` is a standalone executable. The repo's `.zshrc` is the canonical source of the shell function wrappers the user sources from their home `~/.zshrc`.

## Architecture

- `bin/*.sh` — the scripts themselves, all executable. Each script is self-contained and parses its own CLI flags.
- `bin/utils.sh` — shared library, sourced by every other script via:
  ```bash
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  . "$SCRIPT_DIR/utils.sh" --source-only
  ```
  Provides color logging helpers (`log`, `warning`, `info`, `note`, `success`) and `format_bytes` for human-readable sizes.
- `.zshrc` — defines thin shell-function wrappers that `bash`-invoke each script and then call a `playsound-N` notification (defined outside this repo, in the user's environment). When adding a new script, also add a wrapper here so it stays callable by name. The `.zshrc` header comment marks this repo as the **single source of truth** for these wrappers.
- `bin/pre-push.sh` — installed by the user as a git pre-push hook elsewhere; not auto-installed by the repo.
- `bin/version-bump.sh` — vestigial (uses `npm`/`pnpm`/`pnpm changelog`); does not apply to this repo and shouldn't be invoked here.

## Conventions for scripts in `bin/`

- **Shebang**: prefer `#!/usr/bin/env bash`. A few older scripts use `#!/bin/bash` or `#!/opt/homebrew/bin/bash` — leave existing ones alone unless changing behavior.
- **Strict mode**: newer scripts use `set -euo pipefail`. Use it for new scripts.
- **Source utils**: always source `utils.sh` via the `SCRIPT_DIR` pattern above so the script works regardless of CWD.
- **CLI flag style**: long flags with `=` for values (e.g. `--path=/foo`, `--recursive`, `--dry-run`, `--ignore-words=A,B`). Many scripts accept both `--flag` (sets `true`) and `--flag=value` forms — preserve that.
- **Dry-run default**: destructive scripts (rename, delete, fix-codecs) default `DRY_RUN=true`. The `.zshrc` wrapper for `clean-stale-branches` flips this to `false` and exposes a separate `clean-stale-branches-dr` wrapper for the dry-run variant. Match this pattern for new destructive scripts.
- **Version comment**: many scripts have a `# v2.1.0` style comment near the top. Bump it when meaningfully changing behavior.
- **Logging**: use the helpers from `utils.sh` (`log`/`info`/`note`/`warning`/`success`) rather than raw `echo` for status output, so colors stay consistent.
- **File iteration**: use `find ... -print0 | while IFS= read -r -d '' file` for filename safety. Skip macOS metadata files matching `._*`.

## External tool dependencies

Video scripts rely on `ffprobe`/`ffmpeg`, plus `bc` for arithmetic and `perl` for regex-heavy text munging (notably in `rename-video-file.sh`). When adding scripts that need an external binary, follow the `require_binary` pattern in `find-video-mkv-issues.sh`.

## When adding or modifying a script

1. Edit/create the script in `bin/` and `chmod +x` it.
2. If it's new, add a wrapper function to `.zshrc` (with an appropriate `playsound-N` call) so it can be invoked by name from any shell session after the user re-sources their `~/.zshrc`.
3. Keep flag parsing and dry-run semantics consistent with neighboring scripts.
