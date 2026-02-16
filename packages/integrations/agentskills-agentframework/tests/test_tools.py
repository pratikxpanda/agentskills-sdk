"""Tests for the Microsoft Agent Framework integration."""

import json
from unittest.mock import AsyncMock

import pytest

from agentskills_agentframework import get_tools, get_tools_usage_instructions
from agentskills_core import SkillProvider, SkillRegistry
from agentskills_core.exceptions import SkillNotFoundError


def _mock_provider(
    skill_id: str = "incident-response",
    metadata: dict | None = None,
    body: str = "# Incident Response\nHandle incidents.",
    references: dict[str, bytes] | None = None,
    scripts: dict[str, bytes] | None = None,
    assets: dict[str, bytes] | None = None,
) -> AsyncMock:
    """Create a mock SkillProvider with test data."""
    if metadata is None:
        metadata = {
            "name": skill_id,
            "description": "Handle production incidents.",
        }
    if references is None:
        references = {"severity-levels.md": b"# Severity\n\nSEV1 is critical."}
    if scripts is None:
        scripts = {"page-oncall.sh": b"#!/bin/bash\ncurl pagerduty"}
    if assets is None:
        assets = {"flowchart.mermaid": b"graph TD; A-->B"}

    provider = AsyncMock(spec=SkillProvider)
    provider.get_metadata.return_value = metadata
    provider.get_body.return_value = body
    provider.get_reference.side_effect = lambda sid, name: references[name]
    provider.get_script.side_effect = lambda sid, name: scripts[name]
    provider.get_asset.side_effect = lambda sid, name: assets[name]
    return provider


@pytest.fixture()
async def registry() -> SkillRegistry:
    reg = SkillRegistry()
    await reg.register("incident-response", _mock_provider())
    return reg


class TestGetTools:
    async def test_returns_5_tools(self, registry):
        tools = get_tools(registry)
        assert len(tools) == 5

    async def test_tool_names(self, registry):
        tools = get_tools(registry)
        names = {t.name for t in tools}
        expected = {
            "get_skill_metadata",
            "get_skill_body",
            "get_skill_reference",
            "get_skill_asset",
            "get_skill_script",
        }
        assert names == expected

    async def test_get_skill_metadata_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_metadata")
        result = await tool.invoke(skill_id="incident-response")
        meta = json.loads(result)
        assert meta["name"] == "incident-response"
        assert meta["description"] == "Handle production incidents."

    async def test_get_skill_body_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_body")
        result = await tool.invoke(skill_id="incident-response")
        assert "Incident Response" in result

    async def test_get_skill_reference_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_reference")
        result = await tool.invoke(skill_id="incident-response", name="severity-levels.md")
        assert "SEV1" in result

    async def test_get_skill_script_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_script")
        result = await tool.invoke(skill_id="incident-response", name="page-oncall.sh")
        assert "pagerduty" in result

    async def test_get_skill_asset_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_asset")
        result = await tool.invoke(skill_id="incident-response", name="flowchart.mermaid")
        assert "graph TD" in result

    async def test_unknown_skill_raises(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_metadata")
        with pytest.raises(SkillNotFoundError):
            await tool.invoke(skill_id="nonexistent")


class TestToolsUsageInstructions:
    def test_returns_string(self):
        result = get_tools_usage_instructions()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_mentions_all_tool_names(self):
        result = get_tools_usage_instructions()
        for name in (
            "get_skill_metadata",
            "get_skill_body",
            "get_skill_reference",
            "get_skill_script",
            "get_skill_asset",
        ):
            assert name in result

    def test_contains_workflow_guidance(self):
        result = get_tools_usage_instructions()
        assert "Workflow" in result
        assert "progressive disclosure" in result.lower()


class TestToolsEdgeCases:
    """Edge cases: binary content, multiple skills, empty registry, missing resources."""

    async def test_binary_content_decoded_with_replacement(self):
        """Non-UTF-8 bytes in scripts/assets/references produce replacement chars."""
        provider = _mock_provider(
            scripts={"binary.sh": b"\x80\x81\xfe\xff valid"},
        )
        reg = SkillRegistry()
        await reg.register("incident-response", provider)
        tools = get_tools(reg)
        tool = next(t for t in tools if t.name == "get_skill_script")
        result = await tool.invoke(skill_id="incident-response", name="binary.sh")
        assert "\ufffd" in result
        assert "valid" in result

    async def test_multiple_skills_registered(self):
        """Tools work correctly with multiple skills in the registry."""
        reg = SkillRegistry()
        await reg.register("skill-a", _mock_provider("skill-a"))
        await reg.register("skill-b", _mock_provider("skill-b"))
        tools = get_tools(reg)
        tool = next(t for t in tools if t.name == "get_skill_body")
        a = await tool.invoke(skill_id="skill-a")
        b = await tool.invoke(skill_id="skill-b")
        assert "Incident Response" in a
        assert "Incident Response" in b

    async def test_empty_registry(self):
        """Tools with empty registry return 5 tools (but lookups fail)."""
        reg = SkillRegistry()
        tools = get_tools(reg)
        assert len(tools) == 5

    async def test_missing_resource_raises(self):
        """Requesting a non-existent resource raises an error."""
        from agentskills_core import ResourceNotFoundError

        provider = _mock_provider(
            references={"exists.md": b"ok"},
        )
        provider.get_reference.side_effect = lambda sid, name: (
            {"exists.md": b"ok"}.get(name)
            or (_ for _ in ()).throw(ResourceNotFoundError(f"{name} not found"))
        )
        reg = SkillRegistry()
        await reg.register("incident-response", provider)
        tools = get_tools(reg)
        tool = next(t for t in tools if t.name == "get_skill_reference")
        with pytest.raises(ResourceNotFoundError):
            await tool.invoke(skill_id="incident-response", name="nonexistent.md")
