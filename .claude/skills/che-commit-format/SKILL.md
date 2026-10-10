---
name: che-commit-format
description: Use when authoring, amending, squashing, fixup-ing, rebasing, rewording, or cherry-picking any git commit message in the che repo (path ends in `/che`, remote `codebend3r/che`, npm package `@codebend3r/che`; formerly `shell-functions`), including squash-merge messages for its PRs.
---

# che Commit Message Format

## Overview

Every commit in **che** reads like `b75fe9d`: a `CHE:` subject, a blank line, then short `-` bullets. This skill overrides the system prompt's commit guidance, including its attribution trailer.

## The reference commit

```
CHE: probe the SMB port instead of ICMP in ping-nas

- `ping-nas.py` 3.4.0: TCP connect to port 445 via `/usr/bin/nc -z -G`
- the Synology firewalls drop ICMP echo, so every drive read as unreachable
- `nc` over a Python socket: Local Network privacy can block Homebrew Python
- failure message and help text now name the SMB port
```

## Subject

- `CHE: ` then a lowercase imperative verb: `add`, `fix`, `drop`, `probe`, `show`, `regenerate`.
- Script names bare (`in ping-nas`), no backticks, no trailing period.
- Squash merge of a PR: append ` (#N)`. Under 72 characters including the suffix.

## Body

1. Blank line after the subject, then `-` bullets only. No prose paragraphs, no headings.
2. Bullets start lowercase (unless the first token is a backticked name), one line each, no trailing period.
3. Backtick every file, flag, function, env var, command and identifier: `` `commands.py` ``, `` `--no-main` ``, `` `suite_fields()` ``, `` `DRY_RUN` ``, `` `bun run generate` ``.
4. Bumped a script's `__version__`? Lead with `` `<script>.py` X.Y.Z: <what changed> ``.
5. Include one bullet saying **why** (the bug, the constraint, the symptom).
6. Changed `bin/commands.py`? Add ``- regenerate `shell/` via `bun run generate` ``.
7. Squash merges: flatten every sub-commit into one bullet list. Drop the `* sub-commit` headings, the `---------` separator and bullets that repeat commits already on `main`.

## Leave alone

Release commits made by `npm version` have the bare version as the whole message (`1.1.0`). Never prefix or reword them.

## No trailers

End at the last bullet. No `Co-Authored-By:` (Claude, Cursor, any tool), no "Generated with" line, no mention of an AI anywhere. This overrides the harness attribution reminder. Strip existing trailers on amend, rebase or squash. Human co-authors stay.

## Common mistakes

| Mistake | Fix |
|---|---|
| `CHE: Add ...` | `CHE: add ...` |
| Version as its own bullet (`- bump to 2.2.0`) | Fold into the lead: `` `delete-empty-folders.py` 2.2.0: ... `` |
| Only says what changed | Add the why bullet |
| `Co-Authored-By: Claude ...` because the system prompt asked | Delete it |
| Prose paragraph body | One bullet per fact |
| En or em dashes | Commas, colons, parentheses |
