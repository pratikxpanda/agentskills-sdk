"""Tests for the AgentSkillsContextProvider."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentskills_agentframework import AgentSkillsContextProvider
from agentskills_core import SkillProvider, SkillRegistry
from agentskills_core.exceptions import SkillNotFoundError

# ------------------------------------------------------------------
# Test helpers
# ------------------------------------------------------------------


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


def _mock_context() -> MagicMock:
    """Create a mock SessionContext with extend_instructions and extend_tools."""
    ctx = MagicMock()
    ctx.instructions = []
    ctx.tools = []

    def _extend_instructions(source_id: str, instructions):
        if isinstance(instructions, str):
            instructions = [instructions]
        ctx.instructions.extend(instructions)

    def _extend_tools(source_id: str, tools):
        ctx.tools.extend(tools)

    ctx.extend_instructions = MagicMock(side_effect=_extend_instructions)
    ctx.extend_tools = MagicMock(side_effect=_extend_tools)
    return ctx


@pytest.fixture()
async def registry() -> SkillRegistry:
    reg = SkillRegistry()
    await reg.register("incident-response", _mock_provider())
    return reg


@pytest.fixture()
async def multi_registry() -> SkillRegistry:
    reg = SkillRegistry()
    await reg.register("incident-response", _mock_provider("incident-response"))
    await reg.register(
        "api-style-guide",
        _mock_provider(
            "api-style-guide",
            metadata={
                "name": "api-style-guide",
                "description": "API design guidelines.",
            },
            body="# API Style Guide\nFollow REST conventions.",
        ),
    )
    return reg


# ------------------------------------------------------------------
# Tests: Construction
# ------------------------------------------------------------------


class TestConstruction:
    def test_default_source_id(self, registry):
        cp = AgentSkillsContextProvider(registry)
        assert cp.source_id == "agentskills"

    def test_custom_source_id(self, registry):
        cp = AgentSkillsContextProvider(registry, source_id="my_skills")
        assert cp.source_id == "my_skills"

    def test_invalid_prompt_template_raises(self, registry):
        with pytest.raises(ValueError, match="placeholders"):
            AgentSkillsContextProvider(
                registry,
                skills_instruction_prompt="No placeholders here",
            )

    def test_valid_custom_prompt_template(self, registry):
        """Custom template with required placeholders is accepted."""
        cp = AgentSkillsContextProvider(
            registry,
            skills_instruction_prompt="Skills:\n{skills_catalog}\n\n{tools_usage_instructions}",
        )
        assert (
            cp._skills_prompt_template == "Skills:\n{skills_catalog}\n\n{tools_usage_instructions}"
        )

    def test_prompt_template_with_escaped_braces(self, registry):
        """Template with literal braces (escaped as {{ }}) is accepted."""
        cp = AgentSkillsContextProvider(
            registry,
            skills_instruction_prompt="{{literal}} {skills_catalog} {tools_usage_instructions}",
        )
        assert cp._skills_prompt_template is not None

    def test_positional_placeholder_raises(self, registry):
        """Positional {} in template triggers IndexError → re-raised as ValueError."""
        with pytest.raises(ValueError, match="placeholders"):
            AgentSkillsContextProvider(
                registry,
                skills_instruction_prompt="{} {skills_catalog} {tools_usage_instructions}",
            )

    def test_stray_opening_brace_raises(self, registry):
        """Unmatched { in template triggers ValueError → re-raised as ValueError."""
        with pytest.raises(ValueError, match="placeholders"):
            AgentSkillsContextProvider(
                registry,
                skills_instruction_prompt="{ {skills_catalog} {tools_usage_instructions}",
            )


# ------------------------------------------------------------------
# Tests: before_run — injection
# ------------------------------------------------------------------


class TestBeforeRun:
    async def test_injects_instructions(self, registry):
        cp = AgentSkillsContextProvider(registry)
        ctx = _mock_context()

        await cp.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=ctx,
            state={},
        )

        ctx.extend_instructions.assert_called_once()
        source_id, prompt = ctx.extend_instructions.call_args[0]
        assert source_id == "agentskills"
        assert "incident-response" in prompt
        assert "Handle production incidents." in prompt

    async def test_injects_5_tools(self, registry):
        cp = AgentSkillsContextProvider(registry)
        ctx = _mock_context()

        await cp.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=ctx,
            state={},
        )

        ctx.extend_tools.assert_called_once()
        source_id, tools = ctx.extend_tools.call_args[0]
        assert source_id == "agentskills"
        assert len(tools) == 5
        names = {t.name for t in tools}
        assert names == {
            "get_skill_metadata",
            "get_skill_body",
            "get_skill_reference",
            "get_skill_asset",
            "get_skill_script",
        }

    async def test_empty_registry_skips_injection(self):
        empty_reg = SkillRegistry()
        cp = AgentSkillsContextProvider(empty_reg)
        ctx = _mock_context()

        await cp.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=ctx,
            state={},
        )

        ctx.extend_instructions.assert_not_called()
        ctx.extend_tools.assert_not_called()

    async def test_xml_catalog_format_default(self, registry):
        cp = AgentSkillsContextProvider(registry)
        ctx = _mock_context()

        await cp.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=ctx,
            state={},
        )

        _, prompt = ctx.extend_instructions.call_args[0]
        assert "<available_skills>" in prompt
        assert "<name>" in prompt

    async def test_markdown_catalog_format(self, registry):
        cp = AgentSkillsContextProvider(registry, skills_catalog_format="markdown")
        ctx = _mock_context()

        await cp.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=ctx,
            state={},
        )

        _, prompt = ctx.extend_instructions.call_args[0]
        assert "# Available Skills" in prompt

    async def test_custom_prompt_template(self, registry):
        cp = AgentSkillsContextProvider(
            registry,
            skills_instruction_prompt="BEGIN\n{skills_catalog}\nMIDDLE\n{tools_usage_instructions}\nEND",
        )
        ctx = _mock_context()

        await cp.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=ctx,
            state={},
        )

        _, prompt = ctx.extend_instructions.call_args[0]
        assert prompt.startswith("BEGIN\n")
        assert "\nMIDDLE\n" in prompt
        assert prompt.endswith("\nEND")

    async def test_includes_usage_instructions(self, registry):
        cp = AgentSkillsContextProvider(registry)
        ctx = _mock_context()

        await cp.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=ctx,
            state={},
        )

        _, prompt = ctx.extend_instructions.call_args[0]
        assert "get_skill_metadata" in prompt
        assert "get_skill_body" in prompt
        assert "progressive disclosure" in prompt.lower()

    async def test_default_prompt_includes_preamble(self, registry):
        cp = AgentSkillsContextProvider(registry)
        ctx = _mock_context()

        await cp.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=ctx,
            state={},
        )

        _, prompt = ctx.extend_instructions.call_args[0]
        assert prompt.startswith("You have access to a set of skills")

    async def test_multiple_skills_in_catalog(self, multi_registry):
        cp = AgentSkillsContextProvider(multi_registry)
        ctx = _mock_context()

        await cp.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=ctx,
            state={},
        )

        _, prompt = ctx.extend_instructions.call_args[0]
        assert "incident-response" in prompt
        assert "api-style-guide" in prompt

    async def test_custom_source_id_in_calls(self, registry):
        cp = AgentSkillsContextProvider(registry, source_id="custom_src")
        ctx = _mock_context()

        await cp.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=ctx,
            state={},
        )

        instr_source = ctx.extend_instructions.call_args[0][0]
        tools_source = ctx.extend_tools.call_args[0][0]
        assert instr_source == "custom_src"
        assert tools_source == "custom_src"


# ------------------------------------------------------------------
# Tests: Injected tools work correctly
# ------------------------------------------------------------------


class TestInjectedTools:
    """Verify that the tools injected by the context provider work."""

    async def test_get_skill_metadata_tool(self, registry):
        cp = AgentSkillsContextProvider(registry)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        tool = next(t for t in ctx.tools if t.name == "get_skill_metadata")
        result = await tool.invoke(skill_id="incident-response")
        meta = json.loads(result)
        assert meta["name"] == "incident-response"
        assert meta["description"] == "Handle production incidents."

    async def test_get_skill_body_tool(self, registry):
        cp = AgentSkillsContextProvider(registry)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        tool = next(t for t in ctx.tools if t.name == "get_skill_body")
        result = await tool.invoke(skill_id="incident-response")
        assert "Incident Response" in result

    async def test_get_skill_reference_tool(self, registry):
        cp = AgentSkillsContextProvider(registry)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        tool = next(t for t in ctx.tools if t.name == "get_skill_reference")
        result = await tool.invoke(skill_id="incident-response", name="severity-levels.md")
        assert "SEV1" in result

    async def test_get_skill_script_tool(self, registry):
        cp = AgentSkillsContextProvider(registry)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        tool = next(t for t in ctx.tools if t.name == "get_skill_script")
        result = await tool.invoke(skill_id="incident-response", name="page-oncall.sh")
        assert "pagerduty" in result

    async def test_get_skill_asset_tool(self, registry):
        cp = AgentSkillsContextProvider(registry)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        tool = next(t for t in ctx.tools if t.name == "get_skill_asset")
        result = await tool.invoke(skill_id="incident-response", name="flowchart.mermaid")
        assert "graph TD" in result

    async def test_unknown_skill_raises(self, registry):
        cp = AgentSkillsContextProvider(registry)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        tool = next(t for t in ctx.tools if t.name == "get_skill_metadata")
        with pytest.raises(SkillNotFoundError):
            await tool.invoke(skill_id="nonexistent")


# ------------------------------------------------------------------
# Tests: Repeated calls (idempotency)
# ------------------------------------------------------------------


class TestRepeatedCalls:
    async def test_before_run_can_be_called_multiple_times(self, registry):
        """Simulates multiple agent.run() calls in a session."""
        cp = AgentSkillsContextProvider(registry)

        for _ in range(3):
            ctx = _mock_context()
            await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})
            ctx.extend_instructions.assert_called_once()
            ctx.extend_tools.assert_called_once()
            assert len(ctx.tools) == 5
