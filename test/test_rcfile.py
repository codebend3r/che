"""The managed block and the legacy scanner edit the user's dotfiles in place.

The edits are pure text-to-text functions, so most cases need no file at all.
The ones that write go through ``commit_rc`` against a temporary HOME (the
``fake_home`` fixture), so a backup or a write can never land in the
developer's own rc files.
"""

from __future__ import annotations

import machine
import pytest
import rcfile
import shellgen

LEGACY_RC = """\
# my own settings
export EDITOR=nvim
alias ll="ls -la"

# -----------------------------------------------------------------------------
# Shell functions (single source of truth)
# -----------------------------------------------------------------------------

SHELL_FUNCTIONS_BIN="${HOME}/Developer/git/shell-functions/bin"

# Delete local branches whose upstream is gone
clean-stale-branches() {
  DRY_RUN=false python3 "${SHELL_FUNCTIONS_BIN}/git/clean-stale-branches.py"
  playsound-4
}

show-codecs() {
  python3 "${SHELL_FUNCTIONS_BIN}/video/show-codecs.py" "$@"
  playsound-6
}

# something of the user's own that must survive
my-helper() {
  echo "mine"
}

export PATH="$HOME/bin:$PATH"
"""


def block(python: str = "python3") -> str:
    return shellgen.rc_block("zsh", home=machine.REPO, python=python)


# ---------------------------------------------------------------------------
# Block management
# ---------------------------------------------------------------------------


def test_with_block_creates_then_leaves_alone():
    text, action = rcfile.with_block("", block())
    assert action == "created"
    assert shellgen.BEGIN_MARKER in text
    assert rcfile.with_block(text, block()) == (text, "unchanged")


def test_with_block_preserves_the_rest_of_the_file():
    text, _ = rcfile.with_block("# top\nexport EDITOR=nvim\n", block())
    assert text.startswith("# top\nexport EDITOR=nvim\n\n")
    assert text.index("export EDITOR") < text.index(shellgen.BEGIN_MARKER)


def test_with_block_replaces_in_place_without_moving_it():
    text, _ = rcfile.with_block("# before\n", block())
    text += "\n# after the block\n"

    text, action = rcfile.with_block(text, block("/new/python"))
    assert action == "updated"
    assert "/new/python" in text
    assert text.count(shellgen.BEGIN_MARKER) == 1
    assert text.strip().endswith("# after the block")


def test_with_block_survives_a_deleted_end_marker():
    text, _ = rcfile.with_block(f"# top\n{shellgen.BEGIN_MARKER}\nexport CHE_HOME=/old\n", block())
    assert text.count(shellgen.BEGIN_MARKER) == 1
    assert "/old" not in text


def test_without_block_leaves_the_file_as_it_was():
    original = "# top\nexport EDITOR=nvim\n"
    text, _ = rcfile.with_block(original, block())

    assert rcfile.without_block(text).strip() == original.strip()
    assert rcfile.without_block(original) == original


# ---------------------------------------------------------------------------
# Reading and committing
# ---------------------------------------------------------------------------


def test_read_rc_of_a_missing_file_is_empty(fake_home):
    assert rcfile.read_rc(fake_home / ".zshrc") == ""


def test_read_rc_raises_rather_than_reading_an_unreadable_file_as_empty(fake_home):
    """An empty read is what the next edit writes the block over."""
    (fake_home / ".zshrc").mkdir()
    with pytest.raises(OSError):
        rcfile.read_rc(fake_home / ".zshrc")


def test_bytes_that_are_not_utf8_survive_an_edit(fake_home):
    """One Latin-1 byte used to make the whole file read as "" - and the write
    that followed replaced it with nothing but the che block."""
    rc = fake_home / ".zshrc"
    original = b"# caf\xe9 settings\nexport EDITOR=nvim\n"
    rc.write_bytes(original)

    text = rcfile.read_rc(rc)
    updated, _ = rcfile.with_block(text, block())
    rcfile.commit_rc(rc, text, updated)

    written = rc.read_bytes()
    assert written.startswith(original)
    assert shellgen.BEGIN_MARKER.encode() in written


def test_commit_rc_backs_the_file_up_first(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text("# original\n")
    assert rcfile.commit_rc(rc, "# original\n", "# changed\n") is True

    backups = list(machine.backup_dir().glob("zshrc.*.bak"))
    assert [backup.read_text() for backup in backups] == ["# original\n"]
    assert rc.read_text() == "# changed\n"


def test_backups_never_overwrite_each_other(fake_home):
    """Two edits inside one second used to share a backup name, and the second
    copy - of an already-edited file - replaced the only copy of the original."""
    rc = fake_home / ".zshrc"
    for content in ("# one\n", "# two\n", "# three\n"):
        rc.write_text(content)
        rcfile.backup_file(rc)

    backups = sorted(path.read_text() for path in machine.backup_dir().glob("zshrc.*.bak"))
    assert backups == ["# one\n", "# three\n", "# two\n"]


def test_commit_rc_dry_run_touches_nothing(fake_home):
    rc = fake_home / ".zshrc"
    rc.write_text("# untouched\n")

    assert rcfile.commit_rc(rc, "# untouched\n", "# changed\n", dry_run=True) is True
    assert rc.read_text() == "# untouched\n"
    assert not machine.backup_dir().exists()


def test_commit_rc_skips_a_file_that_would_not_change(fake_home):
    rc = fake_home / ".zshrc"
    assert rcfile.commit_rc(rc, "", "") is False
    assert not rc.exists()


# ---------------------------------------------------------------------------
# Legacy wrappers
# ---------------------------------------------------------------------------


def test_find_legacy_names_the_hand_written_wrappers():
    names = rcfile.find_legacy(LEGACY_RC)
    assert "clean-stale-branches" in names
    assert "show-codecs" in names
    assert "my-helper" not in names


def test_without_legacy_keeps_everything_else():
    text, removed = rcfile.without_legacy(LEGACY_RC)

    assert set(removed) == {"clean-stale-branches", "show-codecs"}
    assert "my-helper()" in text
    assert 'export PATH="$HOME/bin:$PATH"' in text
    assert "export EDITOR=nvim" in text
    assert "SHELL_FUNCTIONS_BIN" not in text
    # The comment that documented a removed wrapper goes with it.
    assert "Delete local branches whose upstream is gone" not in text


def test_without_legacy_ignores_the_managed_block():
    with_block, _ = rcfile.with_block(LEGACY_RC, block())
    text, _ = rcfile.without_legacy(with_block)

    assert shellgen.BEGIN_MARKER in text
    assert "SHELL_FUNCTIONS_BIN=" not in text.split(shellgen.BEGIN_MARKER)[0]


TABLE_RC = """\
# my own settings
alias ll="ls -la"

SHELL_FUNCTIONS_BIN="${HOME}/Developer/git/shell-functions/bin"

_sf_run() {
  python3 "${SHELL_FUNCTIONS_BIN}/$1" "${@:2}"
}

# _sf <fn-name> <relative-script> <sound>
_sf() {
  functions[$1]="_sf_run $2"
}

# Git ---
_sf show-codecs   video/show-codecs.py   6
_sf delete-by-ext files/delete-by-ext.py 6

# The user's own automation, which must survive.
morning() {
  sync-all-branches
  mount-all-drives
}
"""


def test_without_legacy_removes_a_table_and_its_helpers():
    """A helper that builds wrappers is legacy too, and so are its call lines:
    deleting `_sf_run` but leaving forty `_sf …` lines would greet every new
    shell with forty "command not found" errors."""
    text, removed = rcfile.without_legacy(TABLE_RC)

    assert {"_sf", "_sf_run"} <= set(removed)
    assert "_sf" not in text
    assert "SHELL_FUNCTIONS_BIN" not in text
    assert 'alias ll="ls -la"' in text


def test_without_legacy_keeps_the_users_own_automation():
    """`morning` calls a wrapper but is not one, so growth must stop there."""
    text, _ = rcfile.without_legacy(TABLE_RC)

    assert "morning() {" in text
    assert "  sync-all-branches" in text
    assert "  mount-all-drives" in text


def test_without_legacy_is_a_no_op_on_a_clean_file():
    assert rcfile.without_legacy("# nothing to see\n") == ("# nothing to see\n", [])


# ---------------------------------------------------------------------------
# Shadowing
# ---------------------------------------------------------------------------


def test_find_shadowing_catches_an_alias():
    text, _ = rcfile.with_block('alias remove-metadata="exiftool -all= "\n', block())
    assert ("remove-metadata", "alias") in rcfile.find_shadowing(text)


def test_find_shadowing_catches_a_later_redefinition():
    text, _ = rcfile.with_block("show-codecs() { echo mine; }\n", block())
    shadowed = dict(rcfile.find_shadowing(text + "\nvideo-list() { echo mine; }\n"))

    # Defined before the block, so the generated wrapper still wins.
    assert "show-codecs" not in shadowed
    assert shadowed["video-list"] == "redefined after the block"


def test_find_shadowing_ignores_unrelated_names():
    text, _ = rcfile.with_block("alias ll='ls -la'\nmy-helper() { echo hi; }\n", block())
    assert rcfile.find_shadowing(text) == []
