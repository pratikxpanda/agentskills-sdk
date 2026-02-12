"""Tests for the MCP server builder."""

import json
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from agentskills_core import SkillProvider, SkillRegistry
from agentskills_mcp import create_mcp_server


def _tool_text(result) -> str:
    """Extract the text from a call_tool result.

    ``FastMCP.call_tool`` returns ``(content_list, structured_content)``
    when ``convert_result=True``.  We want the text of the first content
    block.
    """
    content_list = result[0]
    return content_list[0].text


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


@pytest.fixture()
async def server(registry):
    return create_mcp_server(registry, name="Test Server")


class TestCreateMCPServer:
    async def test_returns_fastmcp_instance(self, server):
        from mcp.server.fastmcp import FastMCP

        assert isinstance(server, FastMCP)

    async def test_server_name(self, server):
        assert server.name == "Test Server"

    async def test_custom_name(self, registry):
        server = create_mcp_server(registry, name="My Skills")
        assert server.name == "My Skills"

    async def test_instructions(self, registry):
        server = create_mcp_server(registry, name="Test", instructions="Test instructions")
        assert server.instructions == "Test instructions"

    async def test_instructions_default_none(self, server):
        assert server.instructions is None

    async def test_registers_5_tools(self, server):
        tools = await server.list_tools()
        assert len(tools) == 5

    async def test_tool_names(self, server):
        tools = await server.list_tools()
        names = {t.name for t in tools}
        expected = {
            "get_skill_metadata",
            "get_skill_body",
            "get_skill_reference",
            "get_skill_asset",
            "get_skill_script",
        }
        assert names == expected

    async def test_registers_3_resources(self, server):
        resources = await server.list_resources()
        assert len(resources) == 3

    async def test_resource_uris(self, server):
        resources = await server.list_resources()
        uris = {str(r.uri) for r in resources}
        assert "skills://catalog/xml" in uris
        assert "skills://catalog/markdown" in uris
        assert "skills://tools-usage-instructions" in uris


class TestMCPTools:
    async def test_get_skill_metadata(self, server):
        result = await server.call_tool("get_skill_metadata", {"skill_id": "incident-response"})
        meta = json.loads(_tool_text(result))
        assert meta["name"] == "incident-response"
        assert meta["description"] == "Handle production incidents."

    async def test_get_skill_body(self, server):
        result = await server.call_tool("get_skill_body", {"skill_id": "incident-response"})
        assert "Incident Response" in _tool_text(result)

    async def test_get_skill_reference(self, server):
        result = await server.call_tool(
            "get_skill_reference",
            {"skill_id": "incident-response", "name": "severity-levels.md"},
        )
        assert "SEV1" in _tool_text(result)

    async def test_get_skill_script(self, server):
        result = await server.call_tool(
            "get_skill_script",
            {"skill_id": "incident-response", "name": "page-oncall.sh"},
        )
        assert "pagerduty" in _tool_text(result)

    async def test_get_skill_asset(self, server):
        result = await server.call_tool(
            "get_skill_asset",
            {"skill_id": "incident-response", "name": "flowchart.mermaid"},
        )
        assert "graph TD" in _tool_text(result)

    async def test_unknown_skill_raises(self, server):
        with pytest.raises(ToolError, match="nope"):
            await server.call_tool("get_skill_metadata", {"skill_id": "nope"})


class TestMCPResources:
    async def test_xml_catalog_contains_skill(self, server):
        contents = await server.read_resource("skills://catalog/xml")
        text = contents[0].content
        assert "<available_skills>" in text
        assert "incident-response" in text

    async def test_xml_catalog_is_xml(self, server):
        contents = await server.read_resource("skills://catalog/xml")
        text = contents[0].content
        assert text.startswith("<available_skills>")
        assert text.endswith("</available_skills>")

    async def test_markdown_catalog_contains_skill(self, server):
        contents = await server.read_resource("skills://catalog/markdown")
        text = contents[0].content
        assert "incident-response" in text

    async def test_markdown_catalog_is_markdown(self, server):
        contents = await server.read_resource("skills://catalog/markdown")
        text = contents[0].content
        assert text.startswith("# Available Skills")

    async def test_instructions_contains_workflow(self, server):
        contents = await server.read_resource("skills://tools-usage-instructions")
        text = contents[0].content
        assert "Workflow" in text
        assert "progressive disclosure" in text.lower()

    async def test_instructions_mentions_all_tools(self, server):
        contents = await server.read_resource("skills://tools-usage-instructions")
        text = contents[0].content
        for name in (
            "get_skill_metadata",
            "get_skill_body",
            "get_skill_reference",
            "get_skill_script",
            "get_skill_asset",
        ):
            assert name in text
