"""``che skills``: install the Claude Code skills that ship with che.

Each directory under the repo's ``skills/`` is one skill (a ``SKILL.md`` and
whatever it references). Installing one symlinks
``~/.claude/skills/<name>`` to it, so ``che update`` (or a ``git pull``) keeps
the installed skill current with no reinstall, and the skill always describes
the scripts of the che it sits beside.

A real directory already at that path is a hand-installed copy, usually the
one these skills were moved in from. It is moved to
``~/.config/che/backups/skills/`` rather than deleted, the same promise the
installer makes for rc files. A symlink pointing somewhere else is replaced;
one already pointing here is left alone. ``--remove`` deletes only links that
point into this repo, never a directory or a link it did not make.

Library module: no shebang, not executable; ``che.py`` dispatches to
:func:`skills_main`.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from commands import REPO
from machine import backup_dir, home, tildify
from report import FAIL, OK, PLAN, SAME, WARN, Listing, Outcome, Tally
from utils import add_bool_flag, build_parser, heading

SOURCE = REPO / "skills"
SKILL_FILE = "SKILL.md"


class Skill(Outcome):
    """Everything installing or removing one skill can conclude, in summary order."""

    LINKED = (OK, "linked", "Linked", Listing.ALL)
    REPLACED = (OK, "replaced", "Replaced, old copy backed up", Listing.ALL)
    UNLINKED = (OK, "removed", "Removed", Listing.ALL)
    WOULD_LINK = (PLAN, "would link", "Would link", Listing.ALL)
    WOULD_REPLACE = (PLAN, "would replace", "Would replace, backing up", Listing.ALL)
    WOULD_UNLINK = (PLAN, "would remove", "Would remove", Listing.ALL)
    CURRENT = (SAME, "", "Already linked", Listing.COUNT)
    ABSENT = (SAME, "", "Not installed", Listing.COUNT)
    NOT_OURS = (WARN, "left alone", "Not che's link, left alone", Listing.ALL)
    FAILED = (FAIL, "failed", "Failed", Listing.ALL)


def default_target() -> Path:
    # Claude Code reads CLAUDE_CONFIG_DIR in place of ~/.claude when it is set.
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(configured) if configured else home() / ".claude") / "skills"


def bundled() -> list[Path]:
    """Every skill directory that ships with this copy of che, by name."""
    if not SOURCE.is_dir():
        return []
    return sorted(path for path in SOURCE.iterdir() if (path / SKILL_FILE).is_file())


@dataclass(frozen=True)
class Link:
    source: Path
    dest: Path

    @property
    def name(self) -> str:
        return self.source.name

    @property
    def is_current(self) -> bool:
        return self.dest.is_symlink() and self.dest.resolve() == self.source.resolve()

    @property
    def is_ours(self) -> bool:
        """A symlink into this repo's skills/, wherever in it it points."""
        if not self.dest.is_symlink():
            return False
        return self.dest.resolve().is_relative_to(SOURCE.resolve())


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir() / "skills" / f"{path.name}-{stamp}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(path, target)
    return target


def install_one(link: Link, tally: Tally[Skill], *, dry_run: bool) -> None:
    if link.is_current:
        tally.record(Skill.CURRENT, link.name)
        return
    occupied = link.dest.exists() or link.dest.is_symlink()
    if dry_run:
        outcome = Skill.WOULD_REPLACE if occupied else Skill.WOULD_LINK
        tally.record(outcome, link.name, tildify(link.dest))
        return
    if not occupied:
        link.dest.parent.mkdir(parents=True, exist_ok=True)
        link.dest.symlink_to(link.source, target_is_directory=True)
        tally.record(Skill.LINKED, link.name, f"{tildify(link.dest)} -> {tildify(link.source)}")
        return
    if link.dest.is_symlink():
        link.dest.unlink()
        detail = "was a link to elsewhere"
    else:
        detail = f"old copy in {tildify(_backup(link.dest))}"
    link.dest.symlink_to(link.source, target_is_directory=True)
    tally.record(Skill.REPLACED, link.name, detail)


def remove_one(link: Link, tally: Tally[Skill], *, dry_run: bool) -> None:
    if not link.dest.exists() and not link.dest.is_symlink():
        tally.record(Skill.ABSENT, link.name)
        return
    if not link.is_ours:
        tally.flag(Skill.NOT_OURS, link.name, tildify(link.dest))
        return
    if dry_run:
        tally.record(Skill.WOULD_UNLINK, link.name, tildify(link.dest))
        return
    link.dest.unlink()
    tally.record(Skill.UNLINKED, link.name, tildify(link.dest))


def sync_skills(*, target: Path, remove: bool = False, dry_run: bool = False) -> int:
    """Link (or with ``remove``, unlink) every bundled skill under ``target``."""
    heading("Claude skills", dry_run=dry_run)
    tally = Tally(Skill)
    action = remove_one if remove else install_one
    for source in bundled():
        try:
            action(Link(source, target / source.name), tally, dry_run=dry_run)
        except OSError as error:
            tally.flag(Skill.FAILED, source.name, error.strerror or str(error))
    tally.summary(
        "Preview" if dry_run else "Summary",
        facts=[f"Target: {tildify(target)}", f"Source: {tildify(SOURCE)}"],
    )
    return 1 if tally.count(Skill.FAILED) else 0


def skills_main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="che skills",
        description="🧠 Link the Claude Code skills that ship with che into ~/.claude/skills.",
    )
    parser.add_argument(
        "--target",
        metavar="DIR",
        type=Path,
        default=None,
        help="Skills directory (default: ~/.claude/skills, or $CLAUDE_CONFIG_DIR/skills)",
    )
    add_bool_flag(parser, "--remove", help="Remove che's links instead of adding them")
    add_bool_flag(parser, "--dry-run", help="Report what would change, change nothing")
    args = parser.parse_args(argv)
    target = (args.target or default_target()).expanduser()
    return sync_skills(target=target, remove=args.remove, dry_run=args.dry_run)
