#!/usr/bin/env python3
"""🔖 Cut a patch version, regenerate the changelog, and re-tag.

VESTIGIAL. This targets a pnpm monorepo with `pnpm changelog` and
`pnpm version:patch` scripts, neither of which exists in this repo. It refuses
to run without --force for that reason.

Usage:
  version-bump.py [--dry-run] [--force]

Options:
  --dry-run   Print each command instead of running it
  --force     Run anyway, despite this not being a pnpm monorepo
  --help      Show help
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    add_bool_flag,
    build_parser,
    info,
    log,
    require_binary,
    run,
    run_cli,
    run_output,
    warning,
)

__version__ = "1.0.1"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="version-bump",
        description="🔖 Cut a patch version, regenerate the changelog, and re-tag.",
    )
    # No DRY_RUN env default here: the shell version had no dry-run at all, and
    # inventing an env hook on a script that rewrites commits and deletes tags
    # would be a new way to get surprised.
    add_bool_flag(parser, "--dry-run", help="Print each command instead of running it")
    add_bool_flag(parser, "--force", help="Run anyway, despite this not being a pnpm monorepo")
    args = parser.parse_args(argv)

    if not args.force:
        # A refusal, not a warning. This deletes a tag and amends a commit; a
        # scary-sounding message followed by doing it anyway is worse than
        # either alternative.
        warning("⚠️  version-bump targets a pnpm monorepo and does not apply to this repo.")
        info("💡 Pass --force if you really mean it.")
        return 1

    # New versus the shell version, which just let the shell report
    # "command not found" and exit 127. Skipped for --dry-run, which runs
    # nothing and should still be able to print the plan anywhere.
    if not args.dry_run:
        require_binary("npm")
        require_binary("pnpm")
        require_binary("git")

    def step(message: str, argv_step: list[str]) -> None:
        log(message)
        if args.dry_run:
            log(f"  🪄 Would run: {' '.join(argv_step)}")
            return
        run(argv_step)

    step("creating patch version", ["npm", "version", "patch"])
    step("generating changelog", ["pnpm", "changelog"])

    # check=False so a dry run still prints the rest of the plan: the tag this
    # describes is created by `npm version patch` above, which dry-run skips,
    # so in a fresh repo `git describe` legitimately has nothing to describe.
    current_tag = run_output(["git", "describe"], check=not args.dry_run)
    if not current_tag:
        current_tag = "<tag from npm version patch>"
    log(f"current tag: {current_tag}")

    step("squashing commits", ["git", "add", "-A"])

    if args.dry_run:
        log("  🪄 Would run: git tag -d " + current_tag)
        log(f"  🪄 Would run: pnpm version:patch  # updates apps to {current_tag}")
        log("  🪄 Would run: git commit --amend -n --no-edit")
        log("  🪄 Would run: git tag " + current_tag)
        return 0

    # The tag has to come off before the amend, because amending rewrites the
    # commit it points at. Wrapped so a failure anywhere in between puts the
    # tag back rather than leaving the repo untagged.
    run(["git", "tag", "-d", current_tag])
    try:
        log(f"updating all apps and libraries with tag version {current_tag}")
        run(["pnpm", "version:patch"])

        # `--amend`: the shell version ran `git cm`, which resolves through the
        # user's `alias.cm = commit --amend`. Without --amend there is no
        # message source at all and the commit aborts, stranding the changes
        # and leaving the tag deleted.
        log("squashing into the previous commit")
        run(["git", "commit", "--amend", "-n", "--no-edit"])
    except BaseException:
        warning(f"↩️  Restoring tag {current_tag}")
        run(["git", "tag", current_tag], check=False)
        raise

    log("re-applying the tag")
    run(["git", "tag", current_tag])
    return 0


if __name__ == "__main__":
    run_cli(main)
