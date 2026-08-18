"""Tests for the single-skill fast path in the MCP server."""

from __future__ import annotations

import pytest

from agentskills_core import SkillRegistry, resolve_fast_path
from agentskills_mcp_server import create_mcp_server
from agentskills_testing import InMemorySkillProvider, build_skill

BODY = "# Incident Response\n\nPage the on-call engineer, then open a channel.\n"


@pytest.fixture
async def registry() -> SkillRegistry:
    reg = SkillRegistry()
    await reg.register(
        "incident-response",
        InMemorySkillProvider({"incident-response": build_skill("incident-response", body=BODY)}),
    )
    return reg


async def _tool_names(server) -> set[str]:
    return {tool.name for tool in await server.list_tools()}


async def _read(server, uri: str) -> str:
    contents = await server.read_resource(uri)
    return "".join(item.content for item in contents)


async def test_the_default_path_registers_all_eight(registry):
    server = create_mcp_server(registry, name="skills")
    assert len(await _tool_names(server)) == 8


async def test_the_fast_path_registers_only_the_resource_tools(registry):
    # MCP has no way to hide a registered tool later, so the body tools
    # are never registered rather than registered and then declined.
    fast_path = await resolve_fast_path(registry)
    server = create_mcp_server(registry, name="skills", fast_path=fast_path)
    assert await _tool_names(server) == {
        "list_skill_resources",
        "get_skill_reference",
        "get_skill_asset",
        "get_skill_script",
    }


async def test_both_catalog_resources_serve_the_body(registry):
    fast_path = await resolve_fast_path(registry)
    server = create_mcp_server(registry, name="skills", fast_path=fast_path)
    for uri in ("skills://catalog/xml", "skills://catalog/markdown"):
        assert "Page the on-call engineer" in await _read(server, uri)


async def test_the_usage_instructions_drop_the_selection_workflow(registry):
    # They would otherwise point the model at a catalog that is no
    # longer there, and at tools that are no longer registered.
    fast_path = await resolve_fast_path(registry)
    server = create_mcp_server(registry, name="skills", fast_path=fast_path)
    text = await _read(server, "skills://tools-usage-instructions")
    assert "get_skill_body" not in text
    assert "get_skill_reference" in text


async def test_the_resource_listing_still_works(registry):
    fast_path = await resolve_fast_path(registry)
    server = create_mcp_server(registry, name="skills", fast_path=fast_path)
    assert "references" in await _read(server, "skills://incident-response/resources")


async def test_the_default_path_still_serves_a_catalog(registry):
    server = create_mcp_server(registry, name="skills")
    assert "incident-response" in await _read(server, "skills://catalog/xml")
