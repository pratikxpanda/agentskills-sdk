"""Tests for ``agentskills serve``."""

from __future__ import annotations

import sys
import types

import pytest

from agentskills_core import SkillUnavailableError
from agentskills_tools.discovery import CliError, SkillLocation
from agentskills_tools.serve import build_native_server, build_registry, create_server


class TestBuildNativeServer:
    async def test_passes_raw_skills_to_native_builder(self, write_skill, skills_root, monkeypatch):
        path = write_skill("alpha")
        (path / "SKILL.md").write_bytes(
            b"\xef\xbb\xbf---\nname: alpha\ndescription: Native\n---\nBody"
        )
        expected = (path / "SKILL.md").read_bytes()
        server = object()
        module = types.ModuleType("agentskills_mcp_server")

        async def build(skills, *, name):
            assert name == "Native test"
            assert [skill.get_id() for skill in skills] == ["alpha"]
            assert await skills[0].read_file("SKILL.md") == expected
            return server

        module.create_native_mcp_server = build
        monkeypatch.setitem(sys.modules, "agentskills_mcp_server", module)

        assert (
            await build_native_server(
                skills_root, [SkillLocation("alpha", path)], name="Native test"
            )
            is server
        )

    async def test_missing_native_support_has_fallback(self, write_skill, skills_root, monkeypatch):
        path = write_skill("alpha")
        monkeypatch.setitem(sys.modules, "agentskills_mcp_server", None)

        with pytest.raises(CliError, match=r"MCP SDK 2\.2.*omit --native"):
            await build_native_server(skills_root, [SkillLocation("alpha", path)], name="Test")

    @pytest.mark.parametrize(
        "error",
        [ValueError("bad manifest"), SkillUnavailableError("drift"), OSError("read failed")],
    )
    async def test_publication_failure_points_to_inspection(
        self, write_skill, skills_root, monkeypatch, error
    ):
        path = write_skill("alpha")
        module = types.ModuleType("agentskills_mcp_server")

        async def build(skills, *, name):
            raise error

        module.create_native_mcp_server = build
        monkeypatch.setitem(sys.modules, "agentskills_mcp_server", module)

        with pytest.raises(CliError, match="agentskills inspect PATH --native"):
            await build_native_server(skills_root, [SkillLocation("alpha", path)], name="Test")


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
