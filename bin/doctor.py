"""``che doctor``: every check on the install, as data first and a table second.

:func:`diagnose` collects the checks as :class:`Check` records, so the table
and ``--json`` can never disagree. Nothing here changes anything; each problem
comes with the command that fixes it.

Library module: no shebang, not executable.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import shellgen
from art import print_logo
from commands import REPO, VERSION, all_commands, required_binaries
from machine import (
    INSTALL_HINTS,
    PYTHON_HINT,
    SHELLS,
    ShellSpec,
    default_shell_selection,
    find_python,
    load_record,
    login_shell,
    python_ok,
    shim_on_path,
    shim_path,
    tildify,
    update_command,
    version_text,
)
from rcfile import ALIAS, find_block, find_legacy, find_shadowing, read_rc
from tui import palette
from utils import add_bool_flag, build_parser, note, success, warning

OK, WARN, FAIL = "ok", "warn", "fail"

ALIAS_FIX = "the alias wins at the prompt; run `\\name` for the wrapper, or remove the alias"


@dataclass(frozen=True)
class Check:
    """One line of the report: what was checked, how it stands, and the fix."""

    name: str
    status: str  # OK, WARN or FAIL
    detail: str
    fix: str = ""
    # A passing check that is noise unless asked for, like a tool that is present.
    quiet: bool = False

    def to_json(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail, "fix": self.fix}


def diagnose() -> list[Check]:
    """Collect every check as data, so both the table and --json use one source."""
    record = load_record()

    python, version = find_python()
    checks = [
        Check(
            "python",
            OK if python_ok(version) else FAIL,
            f"{version_text(version)} ({python})",
            PYTHON_HINT,
        ),
        # Informational: doctor runs from this repo's own che.py, so a repo
        # without one could never have got this far.
        Check("repo", OK, str(REPO)),
    ]

    try:
        stale = shellgen.sync_generated(dry_run=True)
    except ValueError as exc:
        checks.append(Check("generated files", WARN, str(exc), "restore the markers in README.md"))
    else:
        detail = f"{len(stale)} out of date: {', '.join(map(str, stale))}" if stale else "current"
        checks.append(Check("generated files", WARN if stale else OK, detail, "che install"))

    recorded = record.version if record else ""
    checks.append(
        Check(
            "install record",
            OK if recorded == VERSION else (WARN if record else FAIL),
            f"config {recorded or 'missing'} vs che {VERSION}",
            "che install",
        )
    )

    # Only the shells this install actually targets. Reporting on every shell
    # present would flag ~/.profile as "missing" on any machine with /bin/sh,
    # which is every machine.
    watched = {*(record.shells if record else default_shell_selection()), login_shell()}
    for spec in SHELLS.values():
        if spec.name in watched:
            checks += [_rc_check(spec, rc_file) for rc_file in spec.rc_files]

    shim = shim_path()
    if shim.exists() and shim_on_path():
        checks.append(Check("che on PATH", OK, str(shim)))
    elif shim.exists():
        detail = f"{shim} (PATH picks it up on your next shell)"
        checks.append(Check("che on PATH", WARN, detail, f"exec {login_shell() or 'zsh'}"))
    else:
        checks.append(Check("che on PATH", WARN, "not installed", "che install"))

    for binary, users in required_binaries().items():
        found = shutil.which(binary)
        used_by = ", ".join(users[:3]) + (f" +{len(users) - 3}" if len(users) > 3 else "")
        checks.append(
            Check(
                f"tool: {binary}",
                OK if found else WARN,
                found or f"missing - needed by {used_by}",
                INSTALL_HINTS.get(binary, ""),
                quiet=True,
            )
        )

    missing = [
        command.name for command in all_commands() if command.script and not command.path.exists()
    ]
    checks.append(
        Check(
            "scripts",
            OK if not missing else FAIL,
            f"{len(all_commands())} commands"
            + (f", missing: {', '.join(missing)}" if missing else ""),
            update_command(),
        )
    )

    return checks


def _rc_check(spec: ShellSpec, rc_file: Path) -> Check:
    """Whether ``rc_file`` has the block, and whatever in it competes with the block."""
    name = f"{spec.name}: {tildify(rc_file)}"
    try:
        text = read_rc(rc_file)
    except OSError as exc:
        return Check(name, FAIL, f"unreadable ({exc.strerror or exc})", "make it readable")

    has_block = find_block(text) is not None
    legacy = find_legacy(text)
    shadowing = find_shadowing(text)

    if has_block:
        status = WARN if (legacy or shadowing) else OK
    else:
        status = WARN if spec.opt_in else FAIL

    detail = "block installed" if has_block else "no che block"
    if legacy:
        detail += f", {len(legacy)} legacy wrappers"
    if shadowing:
        detail += ", shadowed: " + ", ".join(f"{wrapper} ({how})" for wrapper, how in shadowing[:3])

    if legacy:
        fix = "che install --replace-legacy"
    elif any(how == ALIAS for _, how in shadowing):
        fix = ALIAS_FIX
    elif shadowing:
        fix = "move your definition above the che block"
    else:
        fix = "che install"
    return Check(name, status, detail, fix)


def doctor(*, as_json: bool = False, verbose: bool = False) -> int:
    checks = diagnose()
    failures = sum(1 for check in checks if check.status == FAIL)

    if as_json:
        payload = {"version": VERSION, "checks": [check.to_json() for check in checks]}
        print(json.dumps(payload, indent=2))
        return 1 if failures else 0

    colors = palette()
    marks = {
        OK: f"{colors.green}✓{colors.reset}",
        WARN: f"{colors.yellow}!{colors.reset}",
        FAIL: f"{colors.red}✗{colors.reset}",
    }
    print_logo(f"doctor - che {VERSION}")
    width = max(len(check.name) for check in checks) + 2

    for check in checks:
        if check.status == OK and check.quiet and not verbose:
            continue
        print(
            f"  {marks[check.status]} {check.name:<{width}} {colors.grey}{check.detail}{colors.reset}"
        )
        if check.status != OK and check.fix:
            print(f"    {colors.grey}→ {check.fix}{colors.reset}")

    warnings = sum(1 for check in checks if check.status == WARN)
    print()
    if failures:
        warning(f"{failures} problem(s), {warnings} warning(s).")
    elif warnings:
        note(f"All good, with {warnings} warning(s).")
    else:
        success("Everything checks out.")
    return 1 if failures else 0


def doctor_main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="che doctor", description="🩺 Check the install and everything it depends on."
    )
    add_bool_flag(parser, "--json", help="Machine-readable output")
    add_bool_flag(parser, "--verbose", help="Include checks that passed")
    args = parser.parse_args(argv)
    return doctor(as_json=args.json, verbose=args.verbose)
