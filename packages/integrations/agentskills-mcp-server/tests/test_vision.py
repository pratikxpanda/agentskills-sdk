"""Tests for native image delivery in the MCP server."""

from __future__ import annotations

import base64
import json

import pytest
from mcp.types import ImageContent

from agentskills_core import SkillRegistry
from agentskills_mcp_server import create_mcp_server
from agentskills_testing import InMemorySkillProvider, build_skill

# A real 8x8 red PNG, not just a header, so the assertions are about
# something a model could actually be shown.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEklEQVR4nGP4z8CAFWEXHbQSACj/"
    "P8Fu7N9hAAAAAElFTkSuQmCC"
)
NOT_AN_IMAGE = b"PK\x03\x04\x00\x00 this is a zip \xff\xfe"


@pytest.fixture
async def registry() -> SkillRegistry:
    reg = SkillRegistry()
    await reg.register(
        "incident-response",
        InMemorySkillProvider(
            {
                "incident-response": build_skill(
                    "incident-response",
                    assets={"topology.png": PNG, "archive.png": NOT_AN_IMAGE},
                    references={"runbook.md": b"# Runbook\n"},
                )
            }
        ),
    )
    return reg


def _blocks(result):
    return result[0]


class TestOff:
    async def test_vision_is_off_by_default(self, registry):
        server = create_mcp_server(registry, name="test")
        result = await server.call_tool(
            "get_skill_asset", {"skill_id": "incident-response", "name": "topology.png"}
        )
        (block,) = _blocks(result)
        assert block.type == "text"
        assert json.loads(block.text)["encoding"] == "base64"


class TestOn:
    async def test_an_image_comes_back_as_native_image_content(self, registry):
        server = create_mcp_server(registry, name="test", vision=True)
        result = await server.call_tool(
            "get_skill_asset", {"skill_id": "incident-response", "name": "topology.png"}
        )
        (block,) = _blocks(result)
        assert isinstance(block, ImageContent)
        assert block.mimeType == "image/png"
        assert base64.b64decode(block.data) == PNG

    async def test_references_get_the_same_treatment(self, registry):
        reg = SkillRegistry()
        await reg.register(
            "s",
            InMemorySkillProvider({"s": build_skill("s", references={"diagram.png": PNG})}),
        )
        server = create_mcp_server(reg, name="test", vision=True)
        result = await server.call_tool(
            "get_skill_reference", {"skill_id": "s", "name": "diagram.png"}
        )
        (block,) = _blocks(result)
        assert isinstance(block, ImageContent)

    async def test_text_is_untouched(self, registry):
        server = create_mcp_server(registry, name="test", vision=True)
        result = await server.call_tool(
            "get_skill_reference", {"skill_id": "incident-response", "name": "runbook.md"}
        )
        (block,) = _blocks(result)
        assert block.text == "# Runbook\n"

    async def test_a_file_that_only_claims_to_be_an_image_keeps_the_envelope(self, registry):
        server = create_mcp_server(registry, name="test", vision=True)
        result = await server.call_tool(
            "get_skill_asset", {"skill_id": "incident-response", "name": "archive.png"}
        )
        (block,) = _blocks(result)
        assert block.type == "text"

    async def test_an_image_past_the_ceiling_keeps_the_envelope(self, registry):
        server = create_mcp_server(registry, name="test", vision=True, max_inline_image_bytes=8)
        result = await server.call_tool(
            "get_skill_asset", {"skill_id": "incident-response", "name": "topology.png"}
        )
        (block,) = _blocks(result)
        assert block.type == "text"


class TestToolSurface:
    async def test_vision_does_not_add_or_remove_tools(self, registry):
        plain = {t.name for t in await create_mcp_server(registry, name="a").list_tools()}
        seeing = {
            t.name for t in await create_mcp_server(registry, name="a", vision=True).list_tools()
        }
        assert seeing == plain
