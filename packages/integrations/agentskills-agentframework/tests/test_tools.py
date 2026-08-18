"""Tests for the Microsoft Agent Framework integration."""

import base64
import json

import pytest

from agentskills_agentframework import get_tools, get_tools_usage_instructions
from agentskills_core import SkillRegistry
from agentskills_core.exceptions import SkillNotFoundError
from agentskills_testing import InMemorySkillProvider, build_skill


def _mock_provider(
    skill_id: str = "incident-response",
    metadata: dict | None = None,
    body: str = "# Incident Response\nHandle incidents.",
    references: dict[str, bytes] | None = None,
    scripts: dict[str, bytes] | None = None,
    assets: dict[str, bytes] | None = None,
) -> InMemorySkillProvider:
    """Build a real provider with test data.

    A mock agrees with whatever the test asserts, including the
    assertions that are wrong; :class:`InMemorySkillProvider` passes the
    provider conformance suite, so a test passing against it is evidence
    the code under test would work against a real provider.
    """
    if references is None:
        references = {"severity-levels.md": b"# Severity\n\nSEV1 is critical."}
    if scripts is None:
        scripts = {"page-oncall.sh": b"#!/bin/bash\ncurl pagerduty"}
    if assets is None:
        assets = {"flowchart.mermaid": b"graph TD; A-->B"}

    skill = build_skill(
        skill_id,
        description="Handle production incidents.",
        body=body,
        metadata=metadata,
        references=references,
        scripts=scripts,
        assets=assets,
    )
    return InMemorySkillProvider({skill_id: skill})


async def _invoke_text(tool, **kwargs) -> str:
    """``FunctionTool.invoke`` returns ``list[Content]``; assertions want the payload."""
    return (await tool.invoke(**kwargs))[0].text


@pytest.fixture()
async def registry() -> SkillRegistry:
    reg = SkillRegistry()
    await reg.register("incident-response", _mock_provider())
    return reg


class TestGetTools:
    async def test_returns_8_tools(self, registry):
        tools = get_tools(registry)
        assert len(tools) == 8

    async def test_tool_names(self, registry):
        tools = get_tools(registry)
        names = {t.name for t in tools}
        expected = {
            "get_skill_metadata",
            "get_skill_body",
            "get_skill_outline",
            "get_skill_section",
            "list_skill_resources",
            "get_skill_reference",
            "get_skill_asset",
            "get_skill_script",
        }
        assert names == expected

    async def test_get_skill_metadata_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_metadata")
        result = await _invoke_text(tool, skill_id="incident-response")
        meta = json.loads(result)
        assert meta["name"] == "incident-response"
        assert meta["description"] == "Handle production incidents."

    async def test_get_skill_body_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_body")
        result = await _invoke_text(tool, skill_id="incident-response")
        assert "Incident Response" in result

    async def test_get_skill_outline_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_outline")
        result = await _invoke_text(tool, skill_id="incident-response")
        assert "'incident-response':" in result
        assert "- incident-response " in result

    async def test_get_skill_section_tool(self):
        body = "# Title\n\nIntro.\n\n## Triage\n\nPage the on-call.\n"
        reg = SkillRegistry()
        await reg.register("incident-response", _mock_provider(body=body))
        tools = get_tools(reg)
        tool = next(t for t in tools if t.name == "get_skill_section")
        result = await _invoke_text(tool, skill_id="incident-response", key="triage")
        assert "Page the on-call." in result
        assert "Intro." not in result

    async def test_get_skill_section_unknown_key_raises(self, registry):
        from agentskills_core import SectionNotFoundError

        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_section")
        with pytest.raises(SectionNotFoundError):
            await _invoke_text(tool, skill_id="incident-response", key="nope")

    async def test_get_skill_reference_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_reference")
        result = await _invoke_text(tool, skill_id="incident-response", name="severity-levels.md")
        assert "SEV1" in result

    async def test_list_skill_resources_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "list_skill_resources")
        listing = json.loads(await _invoke_text(tool, skill_id="incident-response"))
        assert listing == {
            "references": ["severity-levels.md"],
            "scripts": ["page-oncall.sh"],
            "assets": ["flowchart.mermaid"],
        }

    async def test_list_skill_resources_reports_unsupported(self):
        """An un-enumerable backend is reported, not raised: the agent can act on it."""
        provider = InMemorySkillProvider(
            {"incident-response": build_skill("incident-response")},
            supports_resource_listing=False,
        )
        reg = SkillRegistry()
        await reg.register("incident-response", provider)

        tool = next(t for t in get_tools(reg) if t.name == "list_skill_resources")
        payload = json.loads(await _invoke_text(tool, skill_id="incident-response"))
        assert payload["supported"] is False
        assert "listing disabled" in payload["note"]

    async def test_get_skill_script_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_script")
        result = await _invoke_text(tool, skill_id="incident-response", name="page-oncall.sh")
        assert "pagerduty" in result

    async def test_get_skill_asset_tool(self, registry):
        tools = get_tools(registry)
        tool = next(t for t in tools if t.name == "get_skill_asset")
        result = await _invoke_text(tool, skill_id="incident-response", name="flowchart.mermaid")
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
            "get_skill_outline",
            "get_skill_section",
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

    async def test_binary_content_returned_as_envelope(self):
        """Non-UTF-8 bytes round-trip as base64 rather than being corrupted."""
        raw = b"\x80\x81\xfe\xff valid"
        provider = _mock_provider(
            scripts={"binary.sh": raw},
        )
        reg = SkillRegistry()
        await reg.register("incident-response", provider)
        tools = get_tools(reg)
        tool = next(t for t in tools if t.name == "get_skill_script")
        result = await _invoke_text(tool, skill_id="incident-response", name="binary.sh")
        envelope = json.loads(result)
        assert "\ufffd" not in result
        assert envelope["encoding"] == "base64"
        assert base64.b64decode(envelope["content"]) == raw

    async def test_oversized_binary_is_described_not_inlined(self):
        provider = _mock_provider(
            assets={"big.bin": b"\xff" * 128},
        )
        reg = SkillRegistry()
        await reg.register("incident-response", provider)
        tools = get_tools(reg, max_inline_binary_bytes=64)
        tool = next(t for t in tools if t.name == "get_skill_asset")
        result = await _invoke_text(tool, skill_id="incident-response", name="big.bin")
        envelope = json.loads(result)
        assert envelope["encoding"] == "none"
        assert "content" not in envelope
        assert envelope["size_bytes"] == 128

    async def test_multiple_skills_registered(self):
        """Tools work correctly with multiple skills in the registry."""
        reg = SkillRegistry()
        await reg.register("skill-a", _mock_provider("skill-a"))
        await reg.register("skill-b", _mock_provider("skill-b"))
        tools = get_tools(reg)
        tool = next(t for t in tools if t.name == "get_skill_body")
        a = await _invoke_text(tool, skill_id="skill-a")
        b = await _invoke_text(tool, skill_id="skill-b")
        assert "Incident Response" in a
        assert "Incident Response" in b

    async def test_empty_registry(self):
        """Tools with empty registry return 8 tools (but lookups fail)."""
        reg = SkillRegistry()
        tools = get_tools(reg)
        assert len(tools) == 8

    async def test_missing_resource_raises(self):
        """Requesting a non-existent resource raises an error."""
        from agentskills_core import ResourceNotFoundError

        provider = _mock_provider(references={"exists.md": b"ok"})
        reg = SkillRegistry()
        await reg.register("incident-response", provider)
        tools = get_tools(reg)
        tool = next(t for t in tools if t.name == "get_skill_reference")
        with pytest.raises(ResourceNotFoundError):
            await tool.invoke(skill_id="incident-response", name="nonexistent.md")
