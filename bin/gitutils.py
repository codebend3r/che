"""Git helpers for the scripts under ``bin/git/``.

Split out of ``utils.py``, which keeps the logging, argument parsing and
subprocess plumbing every script shares. Scripts pick it up the same way::

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from gitutils import skip_git_hooks, worktree_branch_map

Standard library only, like everything else at the ``bin/`` root.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

from utils import info, run, run_output


def skip_git_hooks() -> None:
    """Stop every git this process runs, and every script it spawns, running hooks.

    The branch scripts only check out, rebase and delete branches. A repo's
    hooks (lefthook, husky) gate the user's own commits and pushes, yet
    ``git checkout`` fires post-checkout and ``git rebase`` fires pre-rebase,
    prepare-commit-msg, post-commit and post-rewrite as it replays each
    commit. A hooks path of /dev/null holds no hooks at all.

    It is set through GIT_CONFIG_COUNT (git 2.31+) rather than ``-c`` on each
    call so no git invocation can miss it and a delegated script inherits it.
    Repeat calls are no-ops, so a script and the scripts it delegates to can
    all call it.
    """
    count = int(os.environ.get("GIT_CONFIG_COUNT") or 0)
    for index in range(count):
        if (
            os.environ.get(f"GIT_CONFIG_KEY_{index}") == "core.hooksPath"
            and os.environ.get(f"GIT_CONFIG_VALUE_{index}") == os.devnull
        ):
            return
    os.environ[f"GIT_CONFIG_KEY_{count}"] = "core.hooksPath"
    os.environ[f"GIT_CONFIG_VALUE_{count}"] = os.devnull
    os.environ["GIT_CONFIG_COUNT"] = str(count + 1)


# Set once the remotes are fetched, and inherited by every script delegated to
# after that, so a sync fetches once rather than once per step.
_FETCHED = "CHE_REMOTES_FETCHED"


def fetch_remotes() -> None:
    """``git fetch --all --prune``, once per run however many scripts ask.

    sync-all-branches fetches, then delegates to three scripts that each fetch
    when run on their own. Like :func:`skip_git_hooks`, the marker lives in the
    environment, so a delegated script inherits it and skips its own fetch.
    """
    if os.environ.get(_FETCHED):
        return
    info("📡 Fetching + pruning remotes...")
    # Not wrapped: the shell version ran this bare under `set -e`, so a fetch
    # failure exited with git's own status (128), not a flattened 1.
    run(["git", "fetch", "--all", "--prune", "--quiet"])
    os.environ[_FETCHED] = "1"


# ---------------------------------------------------------------------------
# Refs
# ---------------------------------------------------------------------------


def current_branch(cwd: str | Path | None = None) -> str:
    """The branch checked out in ``cwd``'s worktree, or "" when HEAD is detached.

    The full ref minus ``refs/heads/``, not ``--short``, which reads ``heads/x``
    whenever a tag ``x`` exists (see :func:`local_branches`).
    """
    ref = run_output(["git", "symbolic-ref", "--quiet", "HEAD"], check=False, cwd=cwd)
    return ref.removeprefix("refs/heads/")


def has_tracked_changes(cwd: str | Path | None = None) -> bool:
    """True when ``cwd``'s worktree has uncommitted changes to tracked files.

    Untracked files do not count: checkout and rebase leave them alone, and a
    linked worktree nested inside the main one shows up as untracked.
    """
    return bool(run_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=cwd))


def for_each_ref(
    pattern: str, *fields: str, sort: str = "", cwd: str | Path | None = None
) -> list[list[str]]:
    """``git for-each-ref`` over ``pattern``, one list of ``fields`` per ref.

    Each field is a format atom without its ``%(...)``, so
    ``for_each_ref("refs/remotes/origin", "refname:lstrip=3", "symref")``
    yields ``[branch, symref]`` pairs. ``sort`` is passed as ``--sort``.

    DELIBERATE DIVERGENCE: the shell versions joined fields with ``|``. A
    branch name may legally contain a pipe, and so may an author email, so a
    record like ``a|b[gone]`` split wrong - reporting an upstream a branch did
    not have, or deleting branch ``a``. The fields are joined with \\x01
    instead: control characters are illegal in ref names, so it cannot collide.
    """
    argv = ["git", "for-each-ref", "--format=" + "%01".join(f"%({field})" for field in fields)]
    if sort:
        argv.append(f"--sort={sort}")
    # Another divergence: the shell scripts read refs through `< <(...)`, whose
    # failure does not trip `set -e`, so a failing for-each-ref looked like "no
    # branches" and the script exited 0. Here a failure raises.
    output = run_output([*argv, pattern], cwd=cwd)
    return [line.split("\x01") for line in output.split("\n") if line]


def local_branches(*fields: str, sort: str = "", cwd: str | Path | None = None) -> list[list[str]]:
    """Every local branch as ``[name, *fields]``, through :func:`for_each_ref`.

    The name is ``refname:lstrip=2``, not ``refname:short``: the short form
    becomes ``heads/x`` whenever ``x`` is ambiguous (a tag named like the
    branch, or a local branch called ``origin/x``), and ``git branch -D
    heads/x`` then fails while ``git checkout heads/x`` detaches HEAD.
    """
    return for_each_ref("refs/heads/", "refname:lstrip=2", *fields, sort=sort, cwd=cwd)


# ---------------------------------------------------------------------------
# Worktrees
#
# A branch checked out in a linked worktree cannot be checked out, deleted or
# reset from the main clone - git refuses with "already used by worktree".
# That is a mechanical limit, not a conflict, so every script that touches
# branches needs to know which ones are pinned and where.
# ---------------------------------------------------------------------------


class Worktree(NamedTuple):
    path: str
    branch: str  # "" when detached (or bare): it pins no branch
    locked: bool = False  # `git worktree lock`: git refuses to remove or prune it


def worktrees(cwd: str | Path | None = None) -> list[Worktree]:
    """Every worktree, in ``git worktree list --porcelain`` order.

    The first entry is always the main worktree; callers drop it themselves so
    the distinction stays explicit at the call site.

    DELIBERATE DIVERGENCE: the shell version split on whitespace. NUL-delimited
    porcelain preserves spaces, tabs, backslashes and newlines in paths without
    Git's quoted-path escaping, so commands can route to the exact checkout.
    """
    found: list[Worktree] = []
    for line in run_output(["git", "worktree", "list", "--porcelain", "-z"], cwd=cwd).split("\0"):
        if line.startswith("worktree "):
            found.append(Worktree(line.removeprefix("worktree "), ""))
        elif line.startswith("branch refs/heads/"):
            # Every record opens with its `worktree` line, so this belongs to
            # the last one appended.
            found[-1] = found[-1]._replace(branch=line.removeprefix("branch refs/heads/"))
        elif line == "locked" or line.startswith("locked "):
            found[-1] = found[-1]._replace(locked=True)
    return found


def worktree_branch_map(cwd: str | Path | None = None) -> dict[str, str]:
    """Map ``branch -> worktree path`` for every worktree with a branch checked out.

    Detached worktrees are skipped (they pin no branch). The main worktree IS
    included, because its branch is pinned for exactly the same reason.

    DELIBERATE DIVERGENCE: ``utils.sh`` emitted "<branch>\\t<path>" lines that
    every caller re-parsed. A dict is the same data without the round trip, and
    it cannot be truncated by a path containing a tab.
    """
    mapping: dict[str, str] = {}
    for worktree in worktrees(cwd):
        if worktree.branch:
            # First writer wins: a branch can only be pinned by one worktree,
            # so a duplicate would mean git contradicted itself.
            mapping.setdefault(worktree.branch, worktree.path)
    return mapping


def worktree_is_clean(path: str | Path) -> bool:
    """True when the worktree at ``path`` has no modified or untracked files.

    Ignored build output (node_modules, .next) does not count as dirty, because
    ``git status --porcelain`` does not list ignored paths.
    """
    completed = run(["git", "-C", str(path), "status", "--porcelain"], check=False, capture=True)
    # A non-zero exit means the path is not a working tree at all. Treating
    # that as "clean" would let a caller delete a directory it never inspected.
    if completed.returncode != 0:
        return False
    return not (completed.stdout or "").strip()


# ---------------------------------------------------------------------------
# Operations in progress
#
# A rebase, merge, cherry-pick, revert or bisect leaves state files in the
# worktree's own git dir. A rebase or bisect also detaches HEAD while still
# reserving the branch it started on.
# ---------------------------------------------------------------------------

_OPERATION_FILES = (
    "rebase-merge",
    "rebase-apply",
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "BISECT_START",
)

# Each operation and the command that abandons it, checked in this order.
_ABORTS = (
    ("rebase-merge", ("rebase", "--abort")),
    ("rebase-apply", ("rebase", "--abort")),
    ("MERGE_HEAD", ("merge", "--abort")),
    ("CHERRY_PICK_HEAD", ("cherry-pick", "--abort")),
    ("REVERT_HEAD", ("revert", "--abort")),
    ("BISECT_START", ("bisect", "reset")),
)


def git_path(path: Path, name: str) -> Path:
    result = Path(run_output(["git", "rev-parse", "--git-path", name], cwd=path))
    return result if result.is_absolute() else path / result


def in_progress(path: Path) -> bool:
    return any(git_path(path, name).exists() for name in _OPERATION_FILES)


def abort_operation(path: Path) -> bool:
    """Abandon whatever operation is in progress in ``path``; True when none is left.

    Aborting puts the branch back where the operation found it, so no commit
    is lost: a rebase's replayed commits were never written to the branch.
    """
    for name, command in _ABORTS:
        if git_path(path, name).exists():
            run(["git", *command], cwd=path, check=False, capture=True)
    return not in_progress(path)


def stash_everything(path: Path, message: str) -> str:
    """Stash ``path``'s tracked and untracked changes; return the stash commit, or "".

    "" means there was nothing to stash. Worktrees share one ``refs/stash``, so
    the stash outlives the worktree and ``git stash list`` shows it from any of
    them. Ignored files (node_modules, build output) are left alone.
    """
    if worktree_is_clean(path):
        return ""
    before = run_output(
        ["git", "rev-parse", "--verify", "--quiet", "refs/stash"], cwd=path, check=False
    )
    run(["git", "stash", "push", "--include-untracked", "--message", message], cwd=path)
    after = run_output(
        ["git", "rev-parse", "--verify", "--quiet", "refs/stash"], cwd=path, check=False
    )
    if not after or after == before or not worktree_is_clean(path):
        raise OSError(f"could not stash the changes in {path}")
    return after
