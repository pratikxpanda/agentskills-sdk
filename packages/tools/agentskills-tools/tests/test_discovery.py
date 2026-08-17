"""Tests for skill discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentskills_tools.discovery import CliError, discover, relative_to_cwd


class TestDiscover:
    def test_single_skill_folder_roots_at_the_parent(self, write_skill, skills_root):
        path = write_skill("alpha")

        root, locations = discover(path)

        assert root == skills_root.resolve()
        assert [(loc.skill_id, loc.path) for loc in locations] == [("alpha", path.resolve())]

    def test_collection_returns_every_child_with_a_skill_file(self, write_skill, skills_root):
        write_skill("beta")
        write_skill("alpha")
        (skills_root / "not-a-skill").mkdir()
        (skills_root / "loose.md").write_text("ignored")

        root, locations = discover(skills_root)

        assert root == skills_root.resolve()
        assert [loc.skill_id for loc in locations] == ["alpha", "beta"]

    def test_missing_path_is_a_cli_error(self, tmp_path: Path):
        with pytest.raises(CliError, match="not a directory"):
            discover(tmp_path / "nope")

    def test_file_is_a_cli_error(self, tmp_path: Path):
        target = tmp_path / "SKILL.md"
        target.write_text("---\n---\n")

        with pytest.raises(CliError, match="not a directory"):
            discover(target)

    def test_directory_without_skills_is_a_cli_error(self, skills_root):
        with pytest.raises(CliError, match="no skills found"):
            discover(skills_root)


class TestRelativeToCwd:
    def test_relative_when_below_the_working_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        assert relative_to_cwd(tmp_path / "skills" / "alpha") == "skills/alpha"

    def test_absolute_when_not_below_the_working_directory(self, tmp_path, monkeypatch):
        here = tmp_path / "here"
        here.mkdir()
        elsewhere = tmp_path / "elsewhere"
        monkeypatch.chdir(here)

        assert relative_to_cwd(elsewhere) == elsewhere.as_posix()
