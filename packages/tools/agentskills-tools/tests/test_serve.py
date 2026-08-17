"""Tests for ``agentskills serve``."""

from __future__ import annotations

import sys

import pytest

from agentskills_tools.discovery import CliError, SkillLocation
from agentskills_tools.serve import build_registry, create_server


class TestBuildRegistry:
    async def test_registers_every_skill(self, write_skill, skills_root):
        alpha = write_skill("alpha")
        beta = write_skill("beta")

        registry = await build_registry(
            skills_root, [SkillLocation("alpha", alpha), SkillLocation("beta", beta)]
        )

        assert [skill.get_id() for skill in registry.list_skills()] == ["alpha", "beta"]

    async def test_invalid_skill_points_at_the_command_that_diagnoses_it(
        self, write_skill, skills_root
    ):
        path = write_skill("alpha", "---\nname: alpha\n---\n\nbody")

        with pytest.raises(CliError, match="agentskills validate"):
            await build_registry(skills_root, [SkillLocation("alpha", path)])


class TestCreateServer:
    async def test_builds_a_server(self, write_skill, skills_root):
        path = write_skill("alpha")
        registry = await build_registry(skills_root, [SkillLocation("alpha", path)])

        server = create_server(registry, name="Test")

        assert server is not None

    async def test_missing_extra_explains_how_to_install_it(
        self, write_skill, skills_root, monkeypatch
    ):
        path = write_skill("alpha")
        registry = await build_registry(skills_root, [SkillLocation("alpha", path)])
        monkeypatch.setitem(sys.modules, "agentskills_mcp_server.server", None)

        with pytest.raises(CliError, match=r"agentskills-tools\[serve\]"):
            create_server(registry, name="Test")
