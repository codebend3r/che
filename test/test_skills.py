"""``che skills``: linking the bundled Claude skills, against a temporary HOME."""

from __future__ import annotations

import re

import pytest

import skills


@pytest.fixture
def target(fake_home, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return fake_home / ".claude" / "skills"


def _names():
    return [path.name for path in skills.bundled()]


def test_every_bundled_skill_has_frontmatter_naming_its_directory():
    assert _names(), "no skills under skills/"
    for path in skills.bundled():
        text = (path / skills.SKILL_FILE).read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert re.search(rf"^name: {re.escape(path.name)}$", text, re.MULTILINE)
        assert re.search(r"^description: ", text, re.MULTILINE)


def test_install_links_every_skill(target):
    assert skills.skills_main([]) == 0
    for path in skills.bundled():
        link = target / path.name
        assert link.is_symlink()
        assert link.resolve() == path.resolve()


def test_a_second_install_changes_nothing(target, capsys):
    skills.skills_main([])
    capsys.readouterr()
    assert skills.skills_main([]) == 0
    assert "Already linked" in capsys.readouterr().out


def test_an_existing_copy_is_backed_up_not_deleted(target, fake_home):
    name = _names()[0]
    (target / name).mkdir(parents=True)
    (target / name / "SKILL.md").write_text("old\n", encoding="utf-8")

    assert skills.skills_main([]) == 0

    assert (target / name).is_symlink()
    backups = list((fake_home / ".config" / "che" / "backups" / "skills").iterdir())
    assert [backup.name.startswith(f"{name}-") for backup in backups] == [True]
    assert (backups[0] / "SKILL.md").read_text(encoding="utf-8") == "old\n"


def test_a_link_to_elsewhere_is_replaced(target, tmp_path):
    name = _names()[0]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target.mkdir(parents=True)
    (target / name).symlink_to(elsewhere)

    assert skills.skills_main([]) == 0
    assert (target / name).resolve() == (skills.SOURCE / name).resolve()
    assert elsewhere.is_dir()


def test_dry_run_changes_nothing(target):
    assert skills.skills_main(["--dry-run"]) == 0
    assert not target.exists()


def test_remove_deletes_only_ches_links(target, tmp_path):
    skills.skills_main([])
    mine, theirs = _names()[0], _names()[-1]
    (target / theirs).unlink()
    (target / theirs).mkdir()

    assert skills.skills_main(["--remove"]) == 0

    assert not (target / mine).exists()
    assert (target / theirs).is_dir()


def test_claude_config_dir_moves_the_default_target(fake_home, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(fake_home / "claude-alt"))
    assert skills.skills_main([]) == 0
    assert (fake_home / "claude-alt" / "skills" / _names()[0]).is_symlink()


def test_target_flag_wins(fake_home, tmp_path):
    custom = tmp_path / "custom"
    assert skills.skills_main([f"--target={custom}"]) == 0
    assert (custom / _names()[0]).is_symlink()
