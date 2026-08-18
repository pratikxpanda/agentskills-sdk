"""Tests for the single-skill fast path in the Agent Framework integration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agentskills_agentframework import AgentSkillsContextProvider, get_tools
from agentskills_core import SkillRegistry, resolve_fast_path
from agentskills_testing import InMemorySkillProvider, build_skill

BODY = "# Incident Response\n\nPage the on-call engineer, then open a channel.\n"


def _context() -> MagicMock:
    ctx = MagicMock()
    ctx.instructions = []
    ctx.tools = []
    ctx.metadata = {}
    ctx.response = None
    ctx.extend_instructions = MagicMock(
        side_effect=lambda source_id, text: ctx.instructions.append(text)
    )
    ctx.extend_tools = MagicMock(side_effect=lambda source_id, tools: ctx.tools.extend(tools))
    return ctx


@pytest.fixture
async def registry() -> SkillRegistry:
    reg = SkillRegistry()
    await reg.register(
        "incident-response",
        InMemorySkillProvider({"incident-response": build_skill("incident-response", body=BODY)}),
    )
    return reg


async def _inject(provider) -> MagicMock:
    ctx = _context()
    await provider.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})
    return ctx


class TestTools:
    def test_the_default_path_is_unchanged(self, registry):
        assert len(get_tools(registry)) == 8

    async def test_the_fast_path_drops_the_body_tools(self, registry):
        fast_path = await resolve_fast_path(registry)
        names = {tool.name for tool in get_tools(registry, fast_path=fast_path)}
        assert names == {
            "list_skill_resources",
            "get_skill_reference",
            "get_skill_asset",
            "get_skill_script",
        }


class TestContextProvider:
    async def test_the_body_replaces_the_catalog(self, registry):
        fast_path = await resolve_fast_path(registry)
        ctx = await _inject(AgentSkillsContextProvider(registry, fast_path=fast_path))
        assert "Page the on-call engineer" in ctx.instructions[0]

    async def test_the_selection_workflow_is_gone(self, registry):
        fast_path = await resolve_fast_path(registry)
        ctx = await _inject(AgentSkillsContextProvider(registry, fast_path=fast_path))
        assert "<skills>" not in ctx.instructions[0]
        assert "get_skill_body" not in ctx.instructions[0]

    async def test_only_the_resource_tools_are_attached(self, registry):
        fast_path = await resolve_fast_path(registry)
        ctx = await _inject(AgentSkillsContextProvider(registry, fast_path=fast_path))
        assert len(ctx.tools) == 4

    async def test_the_skill_is_reported_as_already_in_front_of_the_model(self, registry):
        # Its instructions are in the prompt, which is exactly what the
        # loaded set means to any other provider reading this.
        fast_path = await resolve_fast_path(registry)
        ctx = await _inject(AgentSkillsContextProvider(registry, fast_path=fast_path))
        assert ctx.metadata["agentskills_loaded_skills"] == ["incident-response"]

    async def test_the_default_path_is_unchanged(self, registry):
        ctx = await _inject(AgentSkillsContextProvider(registry))
        assert len(ctx.tools) == 8
        assert "get_skill_body" in ctx.instructions[0]

    async def test_it_saves_tokens_against_the_default_path(self, registry):
        # The claim the item rests on: for a small skill the whole
        # apparatus costs more than the content it exists to reach, and
        # the fast path also removes a model round trip that this
        # comparison cannot show.
        fast_path = await resolve_fast_path(registry)
        fast = await _inject(AgentSkillsContextProvider(registry, fast_path=fast_path))
        normal = await _inject(AgentSkillsContextProvider(registry))
        assert len(fast.instructions[0]) < len(normal.instructions[0])

    async def test_repeated_calls_stay_idempotent(self, registry):
        fast_path = await resolve_fast_path(registry)
        provider = AgentSkillsContextProvider(registry, fast_path=fast_path)
        ctx = _context()
        for _ in range(3):
            await provider.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})
        assert len(ctx.instructions) == 1
        assert len(ctx.tools) == 4
