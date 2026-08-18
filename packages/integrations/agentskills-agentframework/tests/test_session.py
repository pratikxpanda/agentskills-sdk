"""Tests for session-aware disclosure: prompt caching and loaded-skill tracking."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agentskills_agentframework import AgentSkillsContextProvider
from agentskills_agentframework.session import (
    LOADED_SKILLS_KEY,
    METADATA_LOADED_SKILLS,
    PROMPT_CACHE_KEY,
    body_loads_in,
)
from agentskills_core import SkillRegistry, estimate_tokens
from agentskills_testing import InMemorySkillProvider, build_skill


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


def _call(name: str, arguments):
    content = MagicMock()
    content.type = "function_call"
    content.name = name
    content.arguments = arguments
    return content


def _response(*contents) -> MagicMock:
    message = MagicMock()
    message.contents = list(contents)
    response = MagicMock()
    response.messages = [message]
    return response


@pytest.fixture
async def registry() -> SkillRegistry:
    """Three skills with realistic catalog entries.

    Selection metadata matters here: a catalog entry that is only a name
    and eight words is cheaper than any reminder that could replace it,
    so a fixture of terse skills would test the decline path by accident.
    """
    reg = SkillRegistry()
    for skill_id, description, when in (
        (
            "incident-response",
            "Triage and mitigate production incidents affecting live traffic.",
            "A production service is returning errors or is unreachable",
        ),
        (
            "api-style-guide",
            "House conventions for designing HTTP APIs: naming, status codes, pagination.",
            "Designing or reviewing a new REST endpoint",
        ),
        (
            "release-process",
            "Cut, tag, and publish a versioned release of a library.",
            "A new version is ready to ship or a release must be rolled back",
        ),
    ):
        await reg.register(
            skill_id,
            InMemorySkillProvider(
                {
                    skill_id: build_skill(
                        skill_id,
                        description=description,
                        body="# Body\n\nText.",
                        metadata={"when_to_use": [when]},
                    )
                }
            ),
        )
    return reg


async def _turn(provider, registry_state, *, response=None) -> MagicMock:
    """Run one full before/after cycle against a fresh context."""
    ctx = _context()
    await provider.before_run(
        agent=MagicMock(), session=MagicMock(), context=ctx, state=registry_state
    )
    ctx.response = response
    await provider.after_run(
        agent=MagicMock(), session=MagicMock(), context=ctx, state=registry_state
    )
    return ctx


class TestBodyLoadDetection:
    def test_a_body_call_is_recorded(self):
        assert body_loads_in(_response(_call("get_skill_body", '{"skill_id": "a"}'))) == ["a"]

    def test_arguments_may_arrive_as_a_mapping(self):
        assert body_loads_in(_response(_call("get_skill_body", {"skill_id": "a"}))) == ["a"]

    def test_a_metadata_call_is_not_a_load(self):
        # Metadata is a catalog entry restated; it is not the instructions.
        assert body_loads_in(_response(_call("get_skill_metadata", '{"skill_id": "a"}'))) == []

    def test_a_section_call_is_not_a_load(self):
        # A section is a fragment. Treating it as "loaded" would prune the
        # catalog entry while most of the skill is still unread.
        assert (
            body_loads_in(_response(_call("get_skill_section", '{"skill_id": "a", "key": "k"}')))
            == []
        )

    def test_malformed_arguments_are_skipped_rather_than_raised_on(self):
        # This runs after a successful turn; a bookkeeping problem must
        # not become a failed run.
        assert body_loads_in(_response(_call("get_skill_body", "not json"))) == []
        assert body_loads_in(_response(_call("get_skill_body", None))) == []
        assert body_loads_in(_response(_call("get_skill_body", '{"other": 1}'))) == []

    def test_non_function_content_is_ignored(self):
        text = MagicMock()
        text.type = "text"
        assert body_loads_in(_response(text)) == []

    def test_no_response_is_no_loads(self):
        assert body_loads_in(None) == []

    def test_several_calls_in_one_turn_are_all_recorded(self):
        response = _response(
            _call("get_skill_body", '{"skill_id": "a"}'),
            _call("get_skill_body", '{"skill_id": "b"}'),
        )
        assert body_loads_in(response) == ["a", "b"]


class TestTracking:
    async def test_a_loaded_skill_is_recorded_in_state(self, registry):
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        await _turn(
            provider, state, response=_response(_call("get_skill_body", '{"skill_id": "a"}'))
        )
        assert state[LOADED_SKILLS_KEY] == ["a"]

    async def test_loads_accumulate_across_turns_without_duplicating(self, registry):
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        for _ in range(2):
            await _turn(
                provider,
                state,
                response=_response(_call("get_skill_body", '{"skill_id": "a"}')),
            )
        await _turn(
            provider, state, response=_response(_call("get_skill_body", '{"skill_id": "b"}'))
        )
        assert state[LOADED_SKILLS_KEY] == ["a", "b"]

    async def test_state_holds_only_json_compatible_values(self, registry):
        # A host is entitled to serialise the session; a set would not survive.
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        await _turn(
            provider, state, response=_response(_call("get_skill_body", '{"skill_id": "a"}'))
        )
        assert isinstance(state[LOADED_SKILLS_KEY], list)

    async def test_the_loaded_set_is_published_for_other_providers(self, registry):
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        ctx = await _turn(
            provider,
            state,
            response=_response(_call("get_skill_body", '{"skill_id": "incident-response"}')),
        )
        assert ctx.metadata[METADATA_LOADED_SKILLS] == ["incident-response"]

    async def test_a_turn_with_no_loads_leaves_state_untouched(self, registry):
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        await _turn(provider, state, response=_response(_call("get_skill_metadata", "{}")))
        assert LOADED_SKILLS_KEY not in state


class TestPruning:
    async def test_turn_two_is_smaller_than_turn_one(self, registry):
        # The whole point of the item: instructions already in the
        # conversation are not paid for again in the catalog.
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        first = await _turn(
            provider,
            state,
            response=_response(_call("get_skill_body", '{"skill_id": "incident-response"}')),
        )
        second = await _turn(provider, state)
        assert len(second.instructions[0]) < len(first.instructions[0])

    async def test_turn_two_costs_measurably_fewer_tokens(self, registry):
        # Measured with the same counter the outline and `inspect --cost`
        # use, so the three cannot disagree about what a prompt costs.
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        first = await _turn(
            provider,
            state,
            response=_response(_call("get_skill_body", '{"skill_id": "incident-response"}')),
        )
        second = await _turn(provider, state)
        assert estimate_tokens(second.instructions[0]) < estimate_tokens(first.instructions[0])

    async def test_a_loaded_skill_still_gets_a_reminder(self, registry):
        # Dropping it silently would let the agent conclude the skill
        # does not exist.
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        await _turn(
            provider,
            state,
            response=_response(_call("get_skill_body", '{"skill_id": "incident-response"}')),
        )
        second = await _turn(provider, state)
        assert (
            "Already loaded, full instructions earlier in this conversation: "
            in (second.instructions[0])
        )
        assert "incident-response" in second.instructions[0]

    async def test_unloaded_skills_are_still_advertised(self, registry):
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        await _turn(
            provider,
            state,
            response=_response(_call("get_skill_body", '{"skill_id": "incident-response"}')),
        )
        second = await _turn(provider, state)
        assert "api-style-guide" in second.instructions[0]
        assert "release-process" in second.instructions[0]

    async def test_the_pruned_catalog_reports_its_own_shortfall(self, registry):
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        await _turn(
            provider,
            state,
            response=_response(_call("get_skill_body", '{"skill_id": "incident-response"}')),
        )
        second = await _turn(provider, state)
        assert 'shown="2"' in second.instructions[0]
        assert 'total="3"' in second.instructions[0]

    async def test_loading_every_skill_restores_the_full_catalog(self, registry):
        # Pruning everything would produce a catalog saying the agent has
        # no skills, which is a worse lie than repeating what it read.
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        await _turn(
            provider,
            state,
            response=_response(
                *(
                    _call("get_skill_body", f'{{"skill_id": "{skill.get_id()}"}}')
                    for skill in registry.list_skills()
                )
            ),
        )
        second = await _turn(provider, state)
        for skill in registry.list_skills():
            assert skill.get_id() in second.instructions[0]
        assert "Already loaded" not in second.instructions[0]

    async def test_pruning_is_declined_when_the_reminder_would_cost_more(self):
        # The reminder is a fixed cost and a catalog entry is not, so for
        # very terse skills pruning can make turn N+1 bigger. Declining is
        # quieter than shipping the one regression the feature exists to
        # prevent.
        reg = SkillRegistry()
        for skill_id in ("a", "b"):
            await reg.register(
                skill_id, InMemorySkillProvider({skill_id: build_skill(skill_id, description="x")})
            )
        provider = AgentSkillsContextProvider(reg)
        state: dict = {}
        first = await _turn(
            provider, state, response=_response(_call("get_skill_body", '{"skill_id": "a"}'))
        )
        second = await _turn(provider, state)
        assert second.instructions[0] == first.instructions[0]

    async def test_a_load_of_a_skill_that_is_not_registered_prunes_nothing(self, registry):
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        await _turn(
            provider, state, response=_response(_call("get_skill_body", '{"skill_id": "ghost"}'))
        )
        second = await _turn(provider, state)
        assert "Already loaded" not in second.instructions[0]

    async def test_pruning_can_be_switched_off(self, registry):
        provider = AgentSkillsContextProvider(registry, prune_loaded_skills=False)
        state: dict = {}
        first = await _turn(
            provider,
            state,
            response=_response(_call("get_skill_body", '{"skill_id": "incident-response"}')),
        )
        second = await _turn(provider, state)
        assert second.instructions[0] == first.instructions[0]
        # Tracking still happens; only the pruning is disabled.
        assert state[LOADED_SKILLS_KEY] == ["incident-response"]


class TestCaching:
    async def test_the_registry_is_not_re_read_on_an_unchanged_turn(self, registry):
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        await _turn(provider, state)

        registry.get_skills_catalog = MagicMock(side_effect=AssertionError("rebuilt"))
        second = await _turn(provider, state)
        assert second.instructions[0] == state[PROMPT_CACHE_KEY]["prompt"]

    async def test_caching_can_be_switched_off(self, registry):
        provider = AgentSkillsContextProvider(registry, cache_prompt=False)
        state: dict = {}
        await _turn(provider, state)
        assert PROMPT_CACHE_KEY not in state

    async def test_a_newly_loaded_skill_invalidates_the_cache(self, registry):
        # Otherwise turn two would serve turn one's un-pruned prompt.
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        first = await _turn(
            provider,
            state,
            response=_response(_call("get_skill_body", '{"skill_id": "incident-response"}')),
        )
        second = await _turn(provider, state)
        assert second.instructions[0] != first.instructions[0]

    async def test_a_newly_registered_skill_invalidates_the_cache(self, registry):
        provider = AgentSkillsContextProvider(registry)
        state: dict = {}
        first = await _turn(provider, state)

        await registry.register(
            "cost-control",
            InMemorySkillProvider({"cost-control": build_skill("cost-control")}),
        )
        second = await _turn(provider, state)
        assert "cost-control" in second.instructions[0]
        assert second.instructions[0] != first.instructions[0]

    async def test_the_catalog_format_is_part_of_the_cache_key(self, registry):
        state: dict = {}
        xml = await _turn(AgentSkillsContextProvider(registry), state)
        markdown = await _turn(
            AgentSkillsContextProvider(registry, skills_catalog_format="markdown"), state
        )
        assert "# Available Skills" in markdown.instructions[0]
        assert markdown.instructions[0] != xml.instructions[0]


class TestIdempotency:
    async def test_a_second_before_run_on_the_same_context_injects_nothing(self, registry):
        # A pipeline that retries a run must not double the prompt.
        provider = AgentSkillsContextProvider(registry)
        ctx = _context()
        state: dict = {}
        for _ in range(3):
            await provider.before_run(
                agent=MagicMock(), session=MagicMock(), context=ctx, state=state
            )
        assert len(ctx.instructions) == 1
        assert len(ctx.tools) == 8

    async def test_two_providers_on_one_context_both_contribute(self, registry):
        # The guard is per source_id, not global: two registries behind
        # two providers is a supported arrangement.
        ctx = _context()
        for source_id in ("skills-a", "skills-b"):
            await AgentSkillsContextProvider(registry, source_id=source_id).before_run(
                agent=MagicMock(), session=MagicMock(), context=ctx, state={}
            )
        assert len(ctx.instructions) == 2

    async def test_an_empty_registry_still_injects_nothing(self):
        provider = AgentSkillsContextProvider(SkillRegistry())
        ctx = _context()
        await provider.before_run(agent=MagicMock(), session=MagicMock(), context=ctx, state={})
        assert ctx.instructions == []
        assert ctx.tools == []

    async def test_after_run_without_before_run_is_harmless(self, registry):
        provider = AgentSkillsContextProvider(registry)
        ctx = _context()
        ctx.response = _response(_call("get_skill_body", '{"skill_id": "a"}'))
        state: dict = {}
        await provider.after_run(agent=MagicMock(), session=MagicMock(), context=ctx, state=state)
        assert state[LOADED_SKILLS_KEY] == ["a"]
