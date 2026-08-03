"""Tests for ``agentskills init``."""

from __future__ import annotations

import pytest

from agentskills_cli.discovery import CliError
from agentskills_cli.scaffold import RESOURCE_DIRS, _TemplateProvider, init_skill, render_skill_md
from agentskills_core import ResourceNotFoundError


class TestInitSkill:
    async def test_creates_a_skill_that_validates(self, tmp_path):
        from agentskills_cli.discovery import discover
        from agentskills_cli.validate import validate_locations

        target = await init_skill("incident-response", tmp_path)

        assert (target / "SKILL.md").is_file()
        assert all((target / d).is_dir() for d in RESOURCE_DIRS)
        assert all(report.ok for report in await validate_locations(*discover(target)))

    async def test_title_is_derived_from_the_name(self, tmp_path):
        target = await init_skill("incident-response", tmp_path)

        assert "# Incident Response" in (target / "SKILL.md").read_text()

    async def test_custom_description_is_used(self, tmp_path):
        target = await init_skill("alpha", tmp_path, "Describes the alpha process.")

        assert "description: Describes the alpha process." in (target / "SKILL.md").read_text()

    async def test_empty_name_is_refused(self, tmp_path):
        with pytest.raises(CliError, match="must not be empty"):
            await init_skill("   ", tmp_path)

    async def test_name_is_checked_against_the_specification(self, tmp_path):
        with pytest.raises(CliError, match="lowercase"):
            await init_skill("Not Valid", tmp_path)

        assert not (tmp_path / "Not Valid").exists()

    async def test_existing_skill_is_not_overwritten(self, tmp_path):
        await init_skill("alpha", tmp_path)

        with pytest.raises(CliError, match="already exists"):
            await init_skill("alpha", tmp_path)

    async def test_unwritable_parent_is_a_cli_error(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")

        with pytest.raises(CliError, match="cannot write"):
            await init_skill("alpha", blocker)


class TestTemplateProvider:
    """The template has no resources; asking for one is an error, not empty bytes."""

    async def test_resource_lookups_fail(self):
        provider = _TemplateProvider({"name": "alpha"}, "body")

        for lookup in (provider.get_script, provider.get_asset, provider.get_reference):
            with pytest.raises(ResourceNotFoundError, match="Template has no"):
                await lookup("alpha", "anything")


class TestRenderSkillMd:
    def test_frontmatter_precedes_the_body(self):
        text = render_skill_md("alpha", "A skill.")

        assert text.startswith("---\nname: alpha\ndescription: A skill.\nversion: 0.1.0\n---\n")
        assert "# Alpha" in text
