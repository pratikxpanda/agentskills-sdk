"""Tests for native image delivery in the Agent Framework tools."""

from __future__ import annotations

import base64
import json

import pytest

from agentskills_agentframework import get_tools
from agentskills_core import SkillRegistry
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


async def _call(tools, tool_name, **arguments):
    tool = next(t for t in tools if t.name == tool_name)
    return await tool.func(**arguments)


class TestOff:
    async def test_vision_is_off_by_default(self, registry):
        result = await _call(
            get_tools(registry),
            "get_skill_asset",
            skill_id="incident-response",
            name="topology.png",
        )
        assert isinstance(result, str)
        assert json.loads(result)["encoding"] == "base64"


class TestOn:
    async def test_an_image_comes_back_as_native_data_content(self, registry):
        result = await _call(
            get_tools(registry, vision=True),
            "get_skill_asset",
            skill_id="incident-response",
            name="topology.png",
        )
        assert result.type == "data"
        assert result.media_type == "image/png"
        assert result.uri == f"data:image/png;base64,{base64.b64encode(PNG).decode('ascii')}"

    async def test_references_get_the_same_treatment(self, registry):
        reg = SkillRegistry()
        await reg.register(
            "s",
            InMemorySkillProvider({"s": build_skill("s", references={"diagram.png": PNG})}),
        )
        result = await _call(
            get_tools(reg, vision=True), "get_skill_reference", skill_id="s", name="diagram.png"
        )
        assert result.media_type == "image/png"

    async def test_text_is_untouched(self, registry):
        result = await _call(
            get_tools(registry, vision=True),
            "get_skill_reference",
            skill_id="incident-response",
            name="runbook.md",
        )
        assert result == "# Runbook\n"

    async def test_a_file_that_only_claims_to_be_an_image_keeps_the_envelope(self, registry):
        result = await _call(
            get_tools(registry, vision=True),
            "get_skill_asset",
            skill_id="incident-response",
            name="archive.png",
        )
        assert isinstance(result, str)

    async def test_an_image_past_the_ceiling_keeps_the_envelope(self, registry):
        result = await _call(
            get_tools(registry, vision=True, max_inline_image_bytes=8),
            "get_skill_asset",
            skill_id="incident-response",
            name="topology.png",
        )
        assert isinstance(result, str)


class TestToolSurface:
    def test_vision_does_not_add_or_remove_tools(self, registry):
        assert {t.name for t in get_tools(registry, vision=True)} == {
            t.name for t in get_tools(registry)
        }
