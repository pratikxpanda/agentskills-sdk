"""Tests for ``agentskills serve``."""

from __future__ import annotations

import sys
import types

import pytest

from agentskills_core import SkillUnavailableError
from agentskills_tools.discovery import CliError, SkillLocation
from agentskills_tools.serve import build_server


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

        module.create_mcp_server = build
        monkeypatch.setitem(sys.modules, "agentskills_mcp_server", module)

        assert (
            await build_server(skills_root, [SkillLocation("alpha", path)], name="Native test")
            is server
        )

    async def test_missing_native_support_has_install_guidance(
        self, write_skill, skills_root, monkeypatch
    ):
        path = write_skill("alpha")
        monkeypatch.setitem(sys.modules, "agentskills_mcp_server", None)

        with pytest.raises(CliError, match=r"MCP SDK 2\.2.*agentskills-tools\[serve\]"):
            await build_server(skills_root, [SkillLocation("alpha", path)], name="Test")

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

        module.create_mcp_server = build
        monkeypatch.setitem(sys.modules, "agentskills_mcp_server", module)

        with pytest.raises(CliError, match="agentskills inspect PATH --native"):
            await build_server(skills_root, [SkillLocation("alpha", path)], name="Test")
