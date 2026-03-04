"""Tests for AgentSkillsContextProvider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentskills_agentframework import AgentSkillsContextProvider
from agentskills_agentframework.context_provider import _CATALOG_CACHE_KEY
from agentskills_core import SkillProvider, SkillRegistry


def _mock_provider(
    skill_id: str = "incident-response",
    metadata: dict | None = None,
    body: str = "# Incident Response\nHandle incidents.",
) -> AsyncMock:
    """Create a minimal mock SkillProvider for catalog tests."""
    if metadata is None:
        metadata = {
            "name": skill_id,
            "description": "Handle production incidents.",
        }
    provider = AsyncMock(spec=SkillProvider)
    provider.get_metadata.return_value = metadata
    provider.get_body.return_value = body
    return provider


@pytest.fixture()
async def registry() -> SkillRegistry:
    reg = SkillRegistry()
    await reg.register("incident-response", _mock_provider())
    return reg


class TestAgentSkillsContextProviderInit:
    def test_instantiates_with_registry(self, registry):
        provider = AgentSkillsContextProvider(registry)
        assert provider is not None
        assert provider._registry is registry

    def test_default_source_id(self, registry):
        provider = AgentSkillsContextProvider(registry)
        assert provider.source_id == AgentSkillsContextProvider.DEFAULT_SOURCE_ID
        assert provider.source_id == "agentskills_context_provider"

    def test_custom_source_id(self, registry):
        provider = AgentSkillsContextProvider(registry, source_id="my_provider")
        assert provider.source_id == "my_provider"


class TestAgentSkillsContextProviderBeforeRun:
    async def test_extends_instructions_with_catalog_and_usage(self, registry):
        """before_run injects combined catalog + usage instructions."""
        provider = AgentSkillsContextProvider(registry)

        context = MagicMock()
        state: dict = {}

        await provider.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=context,
            state=state,
        )

        context.extend_instructions.assert_called_once()
        call_args = context.extend_instructions.call_args
        source_id_arg, instructions_arg = call_args[0]
        assert source_id_arg == provider.source_id
        # Should contain both catalog and usage instructions text
        assert "incident-response" in instructions_arg
        assert "Agent Skills" in instructions_arg

    async def test_instructions_contain_xml_catalog(self, registry):
        """The injected instructions contain the XML-format catalog."""
        provider = AgentSkillsContextProvider(registry)
        context = MagicMock()
        state: dict = {}

        await provider.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=context,
            state=state,
        )

        instructions = context.extend_instructions.call_args[0][1]
        # XML catalog should contain the skill description
        assert "Handle production incidents." in instructions

    async def test_instructions_contain_tool_usage(self, registry):
        """The injected instructions contain tool usage guidance."""
        from agentskills_agentframework.tools import get_tools_usage_instructions

        provider = AgentSkillsContextProvider(registry)
        context = MagicMock()
        state: dict = {}

        await provider.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=context,
            state=state,
        )

        instructions = context.extend_instructions.call_args[0][1]
        usage = get_tools_usage_instructions()
        assert usage in instructions

    async def test_caching_avoids_repeated_catalog_calls(self, registry):
        """Calling before_run multiple times only fetches the catalog once."""
        provider = AgentSkillsContextProvider(registry)
        context = MagicMock()
        state: dict = {}

        with patch.object(
            registry, "get_skills_catalog", new_callable=AsyncMock, return_value="<catalog/>"
        ) as mock_catalog:
            await provider.before_run(
                agent=MagicMock(),
                session=MagicMock(),
                context=context,
                state=state,
            )
            await provider.before_run(
                agent=MagicMock(),
                session=MagicMock(),
                context=context,
                state=state,
            )
            await provider.before_run(
                agent=MagicMock(),
                session=MagicMock(),
                context=context,
                state=state,
            )

        mock_catalog.assert_called_once_with(format="xml")

    async def test_cache_stored_in_state(self, registry):
        """Catalog is stored in the provider state after first call."""
        provider = AgentSkillsContextProvider(registry)
        context = MagicMock()
        state: dict = {}

        await provider.before_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=context,
            state=state,
        )

        assert _CATALOG_CACHE_KEY in state
        assert isinstance(state[_CATALOG_CACHE_KEY], str)

    async def test_separate_sessions_use_separate_state(self, registry):
        """Different state dicts (separate sessions) each fetch the catalog independently."""
        provider = AgentSkillsContextProvider(registry)

        state_a: dict = {}
        state_b: dict = {}

        with patch.object(
            registry, "get_skills_catalog", new_callable=AsyncMock, return_value="<catalog/>"
        ) as mock_catalog:
            await provider.before_run(
                agent=MagicMock(),
                session=MagicMock(),
                context=MagicMock(),
                state=state_a,
            )
            await provider.before_run(
                agent=MagicMock(),
                session=MagicMock(),
                context=MagicMock(),
                state=state_b,
            )

        assert mock_catalog.call_count == 2

    async def test_extend_instructions_called_every_turn(self, registry):
        """extend_instructions is called on every before_run invocation (not cached)."""
        provider = AgentSkillsContextProvider(registry)
        context = MagicMock()
        state: dict = {}

        for _ in range(3):
            await provider.before_run(
                agent=MagicMock(),
                session=MagicMock(),
                context=context,
                state=state,
            )

        assert context.extend_instructions.call_count == 3
