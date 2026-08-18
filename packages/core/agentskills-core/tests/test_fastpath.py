"""Tests for the single-skill fast path."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from agentskills_core import (
    DEFAULT_FAST_PATH_MAX_TOKENS,
    FAST_PATH_DROPPED_TOOLS,
    FastPath,
    SkillProvider,
    SkillRegistry,
    estimate_tokens,
    resolve_fast_path,
)

#: What a one-skill catalog plus the integrations' usage instructions
#: cost per turn on the normal path, measured with the same counter.
#: The integrations own that text, so this is a recorded observation
#: rather than an import — core must not depend on them.
_NORMAL_PATH_PER_TURN_TOKENS = 506


def _provider(skill_id: str, body: str) -> AsyncMock:
    # Hand-rolled rather than taken from ``agentskills-testing``, which
    # depends on this package.
    provider = AsyncMock(spec=SkillProvider)
    provider.get_metadata.return_value = {"name": skill_id, "description": "Test."}
    provider.get_body.return_value = body
    return provider


async def _registry(**bodies: str) -> SkillRegistry:
    registry = SkillRegistry()
    for skill_id, body in bodies.items():
        await registry.register(skill_id, _provider(skill_id, body))
    return registry


class TestResolution:
    async def test_one_small_skill_takes_the_fast_path(self):
        registry = await _registry(alpha="# Alpha\n\nDo the thing.\n")
        fast_path = await resolve_fast_path(registry)
        assert fast_path is not None
        assert fast_path.skill_id == "alpha"
        assert "Do the thing." in fast_path.body

    async def test_two_skills_do_not(self):
        # A catalog exists to let a model choose. Here there is a choice.
        registry = await _registry(alpha="# A\n", beta="# B\n")
        assert await resolve_fast_path(registry) is None

    async def test_an_empty_registry_does_not(self):
        assert await resolve_fast_path(SkillRegistry()) is None

    async def test_a_set_narrowed_to_one_does(self):
        # Fifty skills narrowed to one by a selector is the same
        # situation; len(list_skills()) == 1 would miss it.
        registry = await _registry(alpha="# A\n", beta="# B\n", gamma="# C\n")
        fast_path = await resolve_fast_path(registry, include=["beta"])
        assert fast_path is not None
        assert fast_path.skill_id == "beta"

    async def test_a_set_narrowed_to_two_does_not(self):
        registry = await _registry(alpha="# A\n", beta="# B\n", gamma="# C\n")
        assert await resolve_fast_path(registry, include=["alpha", "beta"]) is None

    async def test_include_naming_a_missing_skill_narrows_to_nothing(self):
        registry = await _registry(alpha="# A\n")
        assert await resolve_fast_path(registry, include=["ghost"]) is None

    async def test_an_empty_include_is_not_the_same_as_no_include(self):
        # A selector that found nothing has narrowed to zero, which is
        # not a fast path; None means "no narrowing was applied".
        registry = await _registry(alpha="# A\n")
        assert await resolve_fast_path(registry, include=[]) is None
        assert await resolve_fast_path(registry, include=None) is not None


class TestCeiling:
    async def test_an_oversized_body_declines(self):
        # Inlining this on every turn of a long conversation costs more
        # than the single tool call it would save.
        registry = await _registry(alpha="word " * 4000)
        assert await resolve_fast_path(registry) is None

    async def test_the_ceiling_is_configurable(self):
        registry = await _registry(alpha="word " * 4000)
        assert await resolve_fast_path(registry, max_tokens=100_000) is not None

    async def test_a_body_exactly_at_the_ceiling_is_allowed(self):
        body = "x" * (DEFAULT_FAST_PATH_MAX_TOKENS * 4)
        registry = await _registry(alpha=body)
        fast_path = await resolve_fast_path(registry)
        assert fast_path is not None
        assert fast_path.tokens == DEFAULT_FAST_PATH_MAX_TOKENS

    async def test_declining_is_logged_with_both_numbers(self, caplog):
        # Silently switching prompt shape based on content size is how
        # token bills become impossible to explain.
        registry = await _registry(alpha="word " * 4000)
        with caplog.at_level(logging.INFO, logger="agentskills"):
            await resolve_fast_path(registry, max_tokens=50)
        assert "Fast path declined" in caplog.text
        assert "alpha" in caplog.text
        assert "50" in caplog.text

    async def test_the_reported_cost_matches_the_shared_counter(self):
        body = "# Alpha\n\nDo the thing.\n"
        registry = await _registry(alpha=body)
        fast_path = await resolve_fast_path(registry)
        assert fast_path is not None
        assert fast_path.tokens == estimate_tokens(body)

    def test_the_default_ceiling_wins_at_any_conversation_length(self):
        # The normal path pays a catalog plus usage instructions every
        # turn and the body once; the fast path pays a wrapper and the
        # body every turn. An integration knows the body size but not
        # the turn count, so the default must not assume one. If this
        # fails, the constant drifted past the point where the fast path
        # is unconditionally a win.
        wrapper = estimate_tokens(FastPath(skill_id="alpha", body="", tokens=0).prompt)
        per_turn_saved = _NORMAL_PATH_PER_TURN_TOKENS - wrapper
        body = DEFAULT_FAST_PATH_MAX_TOKENS
        for turns in (1, 2, 5, 30, 1000):
            normal = _NORMAL_PATH_PER_TURN_TOKENS * turns + body
            fast = (wrapper + body) * turns
            assert fast < normal, f"fast path loses at {turns} turns"
        assert body < per_turn_saved


class TestPrompt:
    @pytest.fixture
    def fast_path(self) -> FastPath:
        return FastPath(skill_id="alpha", body="# Alpha\n\nDo the thing.\n", tokens=8)

    def test_the_body_is_inlined(self, fast_path):
        assert "Do the thing." in fast_path.prompt

    def test_the_skill_keeps_its_identity(self, fast_path):
        # The agent should be able to attribute its behaviour to a named
        # skill rather than to an anonymous slab of system prompt.
        assert '<skill id="alpha">' in fast_path.prompt

    def test_resource_tools_are_still_explained(self, fast_path):
        # Dropping the usage instructions wholesale would leave the model
        # unaware it can read references at all.
        assert "get_skill_reference" in fast_path.prompt
        assert "get_skill_script" in fast_path.prompt
        assert "get_skill_asset" in fast_path.prompt
        assert "list_skill_resources" in fast_path.prompt

    def test_the_selection_workflow_is_not(self, fast_path):
        # There is nothing to select, and telling the model to pick from
        # a catalog it cannot see invites a hallucinated skill id.
        assert "get_skill_body" not in fast_path.prompt
        assert "catalog" not in fast_path.prompt.lower()

    def test_the_prompt_is_a_thin_wrapper_around_the_body(self, fast_path):
        # The claim the item rests on: for a small skill the whole
        # instruction block is a handful of tokens more than the body.
        assert estimate_tokens(fast_path.prompt) < 400


class TestDroppedTools:
    def test_body_access_tools_are_dropped(self):
        fast_path = FastPath(skill_id="alpha", body="x", tokens=1)
        for name in ("get_skill_body", "get_skill_outline", "get_skill_section"):
            assert not fast_path.keeps(name)

    def test_metadata_is_dropped(self):
        # Metadata answers "should I use this skill", which is the
        # question the fast path exists because nobody is asking.
        assert not FastPath(skill_id="a", body="x", tokens=1).keeps("get_skill_metadata")

    def test_resource_tools_are_kept(self):
        # A skill carrying a 2 MB dataset must not have it inlined
        # because the skill count happened to be one.
        fast_path = FastPath(skill_id="alpha", body="x", tokens=1)
        for name in (
            "list_skill_resources",
            "get_skill_reference",
            "get_skill_script",
            "get_skill_asset",
        ):
            assert fast_path.keeps(name)

    def test_the_dropped_set_is_exactly_the_four_body_tools(self):
        assert sorted(FAST_PATH_DROPPED_TOOLS) == [
            "get_skill_body",
            "get_skill_metadata",
            "get_skill_outline",
            "get_skill_section",
        ]
