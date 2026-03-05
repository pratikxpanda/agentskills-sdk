"""Tests for the AgentSkillsMcpContextProvider."""

from unittest.mock import AsyncMock, MagicMock

import pytest

# ------------------------------------------------------------------
# Test helpers
# ------------------------------------------------------------------


def _mock_mcp_session(
    catalog_text: str = "<available_skills>\n  <skill><name>incident-response</name>"
    "<description>Handle production incidents.</description></skill>\n"
    "</available_skills>",
    instructions_text: str = "## How to Use Agent Skills\n\nUse `get_skill_metadata`.",
) -> AsyncMock:
    """Create a mock MCP ClientSession that returns resources."""
    session = AsyncMock()

    async def _read_resource(uri: str):
        result = MagicMock()
        content = MagicMock()
        if "catalog" in str(uri):
            content.text = catalog_text
        elif "instructions" in str(uri):
            content.text = instructions_text
        else:
            raise ValueError(f"Unknown resource URI: {uri}")
        result.contents = [content]
        return result

    session.read_resource = AsyncMock(side_effect=_read_resource)
    return session


def _mock_context() -> MagicMock:
    """Create a mock SessionContext with extend_instructions."""
    ctx = MagicMock()
    ctx.instructions = []

    def _extend_instructions(source_id: str, instructions):
        if isinstance(instructions, str):
            instructions = [instructions]
        ctx.instructions.extend(instructions)

    ctx.extend_instructions = MagicMock(side_effect=_extend_instructions)
    return ctx


# ------------------------------------------------------------------
# Tests: Construction
# ------------------------------------------------------------------


class TestConstruction:
    def test_default_source_id(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session)
        assert cp.source_id == "agentskills_mcp"

    def test_custom_source_id(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session, source_id="my_mcp_skills")
        assert cp.source_id == "my_mcp_skills"

    def test_default_catalog_format(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session)
        assert cp._skills_catalog_format == "xml"

    def test_markdown_catalog_format(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session, skills_catalog_format="markdown")
        assert cp._skills_catalog_format == "markdown"

    def test_default_prompt_template(self):
        from agentskills_mcp_server.context_provider import (
            _DEFAULT_SKILLS_INSTRUCTION_PROMPT,
            AgentSkillsMcpContextProvider,
        )

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session)
        assert cp._skills_prompt_template == _DEFAULT_SKILLS_INSTRUCTION_PROMPT

    def test_custom_prompt_template(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        template = "Skills:\n{skills_catalog}\n\n{tools_usage_instructions}"
        cp = AgentSkillsMcpContextProvider(session, skills_instruction_prompt=template)
        assert cp._skills_prompt_template == template

    def test_invalid_prompt_template_raises(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        with pytest.raises(ValueError, match="placeholders"):
            AgentSkillsMcpContextProvider(session, skills_instruction_prompt="No placeholders here")

    def test_prompt_template_with_escaped_braces(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(
            session,
            skills_instruction_prompt="{{literal}} {skills_catalog} {tools_usage_instructions}",
        )
        assert cp._skills_prompt_template is not None

    def test_positional_placeholder_raises(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        with pytest.raises(ValueError, match="placeholders"):
            AgentSkillsMcpContextProvider(
                session,
                skills_instruction_prompt="{} {skills_catalog} {tools_usage_instructions}",
            )

    def test_stray_opening_brace_raises(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        with pytest.raises(ValueError, match="placeholders"):
            AgentSkillsMcpContextProvider(
                session,
                skills_instruction_prompt="{ {skills_catalog} {tools_usage_instructions}",
            )

    def test_stores_session(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session)
        assert cp._session is session


# ------------------------------------------------------------------
# Tests: before_run — injection
# ------------------------------------------------------------------


class TestBeforeRun:
    async def test_injects_instructions(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        ctx.extend_instructions.assert_called_once()
        source_id, prompt = ctx.extend_instructions.call_args[0]
        assert source_id == "agentskills_mcp"
        assert "incident-response" in prompt

    async def test_does_not_inject_tools(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        assert not hasattr(ctx, "extend_tools") or not ctx.extend_tools.called

    async def test_reads_xml_catalog_by_default(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        # Verify catalog URI used
        calls = session.read_resource.call_args_list
        catalog_call = calls[0]
        assert "catalog/xml" in str(catalog_call)

    async def test_reads_markdown_catalog_when_configured(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session, skills_catalog_format="markdown")
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        calls = session.read_resource.call_args_list
        catalog_call = calls[0]
        assert "catalog/markdown" in str(catalog_call)

    async def test_reads_instructions_resource(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        calls = session.read_resource.call_args_list
        instructions_call = calls[1]
        assert "tools-usage-instructions" in str(instructions_call)

    async def test_custom_prompt_template(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(
            session,
            skills_instruction_prompt="BEGIN\n{skills_catalog}\nMIDDLE\n{tools_usage_instructions}\nEND",
        )
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        _, prompt = ctx.extend_instructions.call_args[0]
        assert prompt.startswith("BEGIN\n")
        assert "\nMIDDLE\n" in prompt
        assert prompt.endswith("\nEND")

    async def test_default_prompt_includes_preamble(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        _, prompt = ctx.extend_instructions.call_args[0]
        assert prompt.startswith("You have access to a set of skills")

    async def test_includes_catalog_content(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session(
            catalog_text="<available_skills><skill><name>my-skill</name></skill></available_skills>"
        )
        cp = AgentSkillsMcpContextProvider(session)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        _, prompt = ctx.extend_instructions.call_args[0]
        assert "my-skill" in prompt

    async def test_includes_instructions_content(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session(instructions_text="Use get_skill_metadata to discover skills.")
        cp = AgentSkillsMcpContextProvider(session)
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        _, prompt = ctx.extend_instructions.call_args[0]
        assert "get_skill_metadata" in prompt

    async def test_custom_source_id_in_call(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session, source_id="custom_src")
        ctx = _mock_context()

        await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})

        source_id = ctx.extend_instructions.call_args[0][0]
        assert source_id == "custom_src"


# ------------------------------------------------------------------
# Tests: Repeated calls (idempotency)
# ------------------------------------------------------------------


class TestRepeatedCalls:
    async def test_before_run_can_be_called_multiple_times(self):
        from agentskills_mcp_server.context_provider import AgentSkillsMcpContextProvider

        session = _mock_mcp_session()
        cp = AgentSkillsMcpContextProvider(session)

        for _ in range(3):
            ctx = _mock_context()
            await cp.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})
            ctx.extend_instructions.assert_called_once()


# ------------------------------------------------------------------
# Tests: Lazy import via __init__
# ------------------------------------------------------------------


class TestLazyImport:
    def test_import_from_package(self):
        from agentskills_mcp_server import AgentSkillsMcpContextProvider

        assert AgentSkillsMcpContextProvider is not None

    def test_unknown_attribute_raises(self):
        import agentskills_mcp_server

        with pytest.raises(AttributeError, match="no attribute"):
            _ = agentskills_mcp_server.nonexistent_thing
