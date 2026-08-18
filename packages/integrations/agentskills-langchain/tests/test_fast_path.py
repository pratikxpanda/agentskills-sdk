"""Tests for the single-skill fast path in the LangChain integration."""

from __future__ import annotations

import pytest

from agentskills_core import SkillRegistry, estimate_tokens, resolve_fast_path
from agentskills_langchain import get_tools, get_tools_usage_instructions
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


def test_the_default_path_is_unchanged(registry):
    assert len(get_tools(registry)) == 8


async def test_the_fast_path_drops_the_body_tools(registry):
    fast_path = await resolve_fast_path(registry)
    names = {tool.name for tool in get_tools(registry, fast_path=fast_path)}
    assert names == {
        "list_skill_resources",
        "get_skill_reference",
        "get_skill_asset",
        "get_skill_script",
    }


async def test_the_tools_that_remain_still_work(registry):
    # Dropping four must not disturb the four that are left.
    fast_path = await resolve_fast_path(registry)
    tools = {tool.name: tool for tool in get_tools(registry, fast_path=fast_path)}
    result = await tools["list_skill_resources"].coroutine(skill_id="incident-response")
    assert "references" in result


async def test_the_prompt_is_cheaper_than_the_catalog_path(registry):
    fast_path = await resolve_fast_path(registry)
    assert fast_path is not None
    catalog = await registry.get_skills_catalog()
    normal = f"{catalog}\n\n{get_tools_usage_instructions()}"
    assert estimate_tokens(fast_path.prompt) < estimate_tokens(normal)


async def test_the_normal_path_still_costs_what_core_assumes(registry):
    # Core's default ceiling is derived from this number. It lives in
    # the integrations, so core records it rather than importing it —
    # which means it can rot silently unless something checks.
    catalog = await registry.get_skills_catalog()
    normal = f"{catalog}\n\n{get_tools_usage_instructions()}"
    assert 450 <= estimate_tokens(normal) <= 560


async def test_a_registry_of_two_gets_no_fast_path(registry):
    await registry.register(
        "release-process",
        InMemorySkillProvider({"release-process": build_skill("release-process")}),
    )
    assert await resolve_fast_path(registry) is None
    assert len(get_tools(registry, fast_path=None)) == 8
