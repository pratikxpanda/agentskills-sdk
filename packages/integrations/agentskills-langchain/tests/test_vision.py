"""Tests for native image delivery in the LangChain tools."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from agentskills_core import SkillRegistry
from agentskills_langchain import get_tools
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


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


class TestOff:
    async def test_vision_is_off_by_default(self, registry):
        # Handing an image block to a text-only model is an API error,
        # not a worse answer, so the caller opts in.
        result = await _tool(get_tools(registry), "get_skill_asset").ainvoke(
            {"skill_id": "incident-response", "name": "topology.png"}
        )
        assert isinstance(result, str)
        assert json.loads(result)["encoding"] == "base64"

    async def test_the_envelope_is_byte_for_byte_what_it_was(self, registry):
        args = {"skill_id": "incident-response", "name": "topology.png"}
        without = await _tool(get_tools(registry), "get_skill_asset").ainvoke(args)
        explicit = await _tool(get_tools(registry, vision=False), "get_skill_asset").ainvoke(args)
        assert without == explicit


class TestOn:
    async def test_an_image_comes_back_as_a_native_block(self, registry):
        result = await _tool(get_tools(registry, vision=True), "get_skill_asset").ainvoke(
            {"skill_id": "incident-response", "name": "topology.png"}
        )
        assert isinstance(result, list)
        (block,) = result
        assert block["type"] == "image"
        assert block["source_type"] == "base64"
        assert block["mime_type"] == "image/png"
        assert base64.b64decode(block["data"]) == PNG

    async def test_references_get_the_same_treatment(self, registry):
        reg = SkillRegistry()
        await reg.register(
            "s",
            InMemorySkillProvider({"s": build_skill("s", references={"diagram.png": PNG})}),
        )
        result = await _tool(get_tools(reg, vision=True), "get_skill_reference").ainvoke(
            {"skill_id": "s", "name": "diagram.png"}
        )
        assert result[0]["mime_type"] == "image/png"

    async def test_text_is_untouched(self, registry):
        result = await _tool(get_tools(registry, vision=True), "get_skill_reference").ainvoke(
            {"skill_id": "incident-response", "name": "runbook.md"}
        )
        assert result == "# Runbook\n"

    async def test_a_file_that_only_claims_to_be_an_image_keeps_the_envelope(self, registry):
        result = await _tool(get_tools(registry, vision=True), "get_skill_asset").ainvoke(
            {"skill_id": "incident-response", "name": "archive.png"}
        )
        assert isinstance(result, str)
        assert json.loads(result)["encoding"] == "base64"

    async def test_an_image_past_the_ceiling_keeps_the_envelope(self, registry):
        tools = get_tools(registry, vision=True, max_inline_image_bytes=8)
        result = await _tool(tools, "get_skill_asset").ainvoke(
            {"skill_id": "incident-response", "name": "topology.png"}
        )
        assert isinstance(result, str)


class TestToolSurface:
    def test_vision_does_not_add_or_remove_tools(self, registry):
        assert {t.name for t in get_tools(registry, vision=True)} == {
            t.name for t in get_tools(registry)
        }

    def test_the_argument_schema_is_unchanged(self, registry):
        plain = _tool(get_tools(registry), "get_skill_asset")
        seeing = _tool(get_tools(registry, vision=True), "get_skill_asset")
        assert seeing.args == plain.args


class TestTheExampleSkill:
    """End-to-end: a real skill on disk, through a real provider.

    The in-memory fixtures above prove the branching.  This proves the
    whole path, because a PNG that survives a fixture but not a real
    file read would still be a broken feature.
    """

    @pytest.fixture()
    def registry(self):
        # agentskills-fs is a sibling package rather than a declared
        # dependency; it is here because the point being proven is what
        # the model receives, and inventing bytes would not prove it.
        from agentskills_fs import LocalFileSystemSkillProvider

        root = Path(__file__).resolve().parents[4] / "examples" / "skills"
        if not root.is_dir():
            pytest.skip("examples/skills/ not found")

        async def _build():
            reg = SkillRegistry()
            await reg.register("incident-response", LocalFileSystemSkillProvider(root))
            return reg

        return _build()

    async def test_the_bundled_diagram_arrives_as_an_image(self, registry):
        reg = await registry
        result = await _tool(get_tools(reg, vision=True), "get_skill_asset").ainvoke(
            {"skill_id": "incident-response", "name": "severity-ladder.png"}
        )
        (block,) = result
        assert block["type"] == "image"
        assert block["mime_type"] == "image/png"
        assert base64.b64decode(block["data"]).startswith(b"\x89PNG\r\n\x1a\n")

    async def test_the_mermaid_diagram_beside_it_still_arrives_as_text(self, registry):
        # Both are diagrams; only one is worth showing rather than
        # reading.
        reg = await registry
        result = await _tool(get_tools(reg, vision=True), "get_skill_asset").ainvoke(
            {"skill_id": "incident-response", "name": "escalation-flowchart.mermaid"}
        )
        assert isinstance(result, str)
        assert "graph TD" in result
