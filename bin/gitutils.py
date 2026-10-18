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
import sys
from pathlib import Path
from typing import NamedTuple

from utils import info, run, run_output, warning


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


def find_main_branch(cwd: str | Path | None = None) -> str:
    """The local main branch, preferring ``main`` over ``master``, or "" for neither.

    Takes an explicit ``cwd`` because callers run it after moving to the main
    worktree; relying on the process working directory would make the answer
    depend on where the script happened to be invoked from.
    """
    for candidate in ("main", "master"):
        exists = run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"],
            check=False,
            capture=True,
            cwd=cwd,
        )
        if exists.returncode == 0:
            return candidate
    return ""


def park_main_worktree(action: str, *, dry_run: bool) -> Path:
    """Put the main worktree on main (or master) before ``action``; return its path.

    The main worktree, not the one the script was run from: removing a worktree
    fails while standing in it, and the branch scripts expect the main clone.
    Starting from a known-good branch keeps every later step predictable.

    Exits 1 outside a working tree, when there is neither a ``main`` nor a
    ``master``, or when the main worktree has uncommitted changes to tracked
    files (see :func:`has_tracked_changes`). ``dry_run`` reports the switch
    instead of making it.
    """
    # "true" on stdout, not just exit 0: inside a bare repo or a .git directory
    # rev-parse succeeds and prints "false".
    if run_output(["git", "rev-parse", "--is-inside-work-tree"], check=False) != "true":
        warning("❌ Not inside a git working tree.")
        sys.exit(1)

    main_wt = Path(worktrees()[0].path)

    main_branch = find_main_branch(main_wt)
    if not main_branch:
        warning(f"❌ Neither 'main' nor 'master' exists locally — refusing to {action}.")
        sys.exit(1)

    current = current_branch(main_wt)
    if current == main_branch:
        info(f"📍 Main worktree already on 🌿 {main_branch}")
        return main_wt

    if has_tracked_changes(main_wt):
        warning(
            f"❌ Main worktree has uncommitted changes — commit or stash before you {action}. 🧺"
        )
        sys.exit(1)

    if dry_run:
        info(
            f"🌵 Would switch main worktree to 🌿 {main_branch} (currently on {current or 'detached'})"
        )
    else:
        info(f"🔀 Switching main worktree to 🌿 {main_branch} (from {current or 'detached'})")
        run(["git", "checkout", "--quiet", main_branch], cwd=main_wt)
    return main_wt
