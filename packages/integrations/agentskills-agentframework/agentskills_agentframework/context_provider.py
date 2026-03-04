"""Microsoft Agent Framework context provider for Agent Skills.

This module provides :class:`AgentSkillsContextProvider`, which injects the
Agent Skills catalog and tool usage instructions into the agent's conversation
context automatically before each LLM invocation.
"""

from __future__ import annotations

from typing import Any

from agent_framework import AgentSession, BaseContextProvider, SessionContext, SupportsAgentRun

from agentskills_agentframework.tools import get_tools_usage_instructions
from agentskills_core import SkillRegistry

_CATALOG_CACHE_KEY = "_agentskills_catalog"


class AgentSkillsContextProvider(BaseContextProvider):
    """Context provider that injects the Agent Skills catalog and tool usage instructions.

    Subclasses :class:`~agent_framework.BaseContextProvider` and automatically
    injects the skills catalog and tool usage instructions into the agent's
    conversation context before each LLM invocation.

    The catalog is fetched once per session (cached in the provider-scoped
    state dict) to avoid redundant async calls on every turn.

    Args:
        registry: The :class:`~agentskills_core.SkillRegistry` to build the
            catalog from.
        source_id: Unique identifier for this provider instance. Defaults to
            ``"agentskills_context_provider"``.

    Example::

        from agentskills_agentframework import get_tools, AgentSkillsContextProvider

        agent = Agent(
            client=client,
            instructions="You are an SRE assistant.",
            tools=get_tools(registry),
            ai_context_providers=[AgentSkillsContextProvider(registry)],
        )
    """

    DEFAULT_SOURCE_ID: str = "agentskills_context_provider"

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        source_id: str | None = None,
    ) -> None:
        """Initialize the context provider.

        Args:
            registry: The :class:`~agentskills_core.SkillRegistry` to build
                the catalog from.
            source_id: Unique identifier for this provider instance.
        """
        super().__init__(source_id or self.DEFAULT_SOURCE_ID)
        self._registry = registry
        self._usage_instructions = get_tools_usage_instructions()

    async def before_run(
        self,
        *,
        agent: SupportsAgentRun,
        session: AgentSession,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        """Inject skills catalog and usage instructions into the session context.

        The catalog is fetched once per session and cached in ``state`` to
        avoid recomputing on every turn.

        Args:
            agent: The agent running this invocation.
            session: The current session.
            context: The invocation context -- instructions are added here.
            state: The provider-scoped mutable state dict for this session.
        """
        if _CATALOG_CACHE_KEY not in state:
            state[_CATALOG_CACHE_KEY] = await self._registry.get_skills_catalog(format="xml")

        combined = f"{state[_CATALOG_CACHE_KEY]}\n\n{self._usage_instructions}"
        context.extend_instructions(self.source_id, combined)
