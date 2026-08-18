"""Tests for the dependency-free BM25 selector."""

from __future__ import annotations

import logging

from agentskills_core import SkillRegistry
from agentskills_retrieval import LexicalSelector
from agentskills_testing import InMemorySkillProvider, build_skill


async def _registry(**skills: dict[str, object]) -> SkillRegistry:
    registry = SkillRegistry()
    await registry.register(
        [
            (
                skill_id,
                InMemorySkillProvider(
                    {
                        skill_id: build_skill(
                            skill_id,
                            description=str(spec.get("description", "")),
                            metadata={
                                key: value
                                for key, value in spec.items()
                                if key != "description" and value is not None
                            },
                        )
                    }
                ),
            )
            for skill_id, spec in skills.items()
        ]
    )
    return registry


def _score(selection, skill_id: str) -> float:
    """The raw score for *skill_id*, whether it was selected or rejected."""
    return next(
        scored.score
        for scored in [*selection.selected, *selection.rejected]
        if scored.skill_id == skill_id
    )


class TestRanking:
    async def test_the_matching_skill_wins(self):
        registry = await _registry(
            database={"description": "Apply schema migrations to a relational database."},
            onboarding={"description": "Get a new engineer productive in week one."},
        )
        selection = await LexicalSelector(registry).select("run a schema migration")
        assert selection.skill_ids[0] == "database"

    async def test_when_to_use_is_ranked_not_just_the_description(self):
        registry = await _registry(
            target={"description": "House conventions.", "when_to_use": ["A pod is crash-looping"]},
            other={"description": "Write release notes."},
        )
        selection = await LexicalSelector(registry).select("my pod is crash-looping")
        assert selection.skill_ids[0] == "target"

    async def test_tags_are_ranked(self):
        registry = await _registry(
            tagged={"description": "House conventions.", "metadata": {"tags": ["kubernetes"]}},
            other={"description": "Write release notes."},
        )
        selection = await LexicalSelector(registry).select("kubernetes")
        assert selection.skill_ids[0] == "tagged"

    async def test_limit_caps_the_result(self):
        registry = await _registry(
            **{f"skill-{i}": {"description": "Handle a production incident."} for i in range(8)}
        )
        selection = await LexicalSelector(registry).select("production incident", limit=3)
        assert len(selection.selected) == 3

    async def test_scores_are_ordered_best_first(self, labelled):
        selection = await LexicalSelector(labelled).select("the pod is in CrashLoopBackOff")
        scores = [scored.score for scored in selection.selected]
        assert scores == sorted(scores, reverse=True)

    async def test_ties_break_deterministically(self):
        # Identical descriptions score identically; without a tie-break
        # the catalog would vary between runs of the same registry.
        registry = await _registry(
            zebra={"description": "Handle a production incident."},
            alpha={"description": "Handle a production incident."},
            middle={"description": "Handle a production incident."},
        )
        selector = LexicalSelector(registry)
        first = await selector.select("production incident")
        second = await selector.select("production incident")
        assert first.skill_ids == second.skill_ids == ["alpha", "middle", "zebra"]


class TestNegativeConditions:
    async def test_a_disclaimer_demotes_rather_than_matches(self):
        registry = await _registry(
            wrong={
                "description": "Handle production incidents.",
                "when_not_to_use": ["A flaky unit test on a laptop"],
            },
            right={"description": "Fix a flaky unit test."},
        )
        selection = await LexicalSelector(registry).select("flaky unit test")
        assert selection.skill_ids[0] == "right"

    async def test_the_penalty_can_be_switched_off(self):
        registry = await _registry(
            disclaimed={
                "description": "Handle a flaky production incident.",
                "when_not_to_use": ["A flaky unit test"],
            },
            other={"description": "Onboard a new engineer."},
        )
        with_penalty = await LexicalSelector(registry).select("flaky unit test")
        without = await LexicalSelector(registry, negative_weight=0.0).select("flaky unit test")
        assert _score(without, "disclaimed") > _score(with_penalty, "disclaimed")

    async def test_a_disclaimer_alone_never_promotes_a_skill(self):
        # The only vocabulary overlap is inside when_not_to_use, so the
        # score must not clear the floor.
        registry = await _registry(
            disclaimed={"description": "Write release notes.", "when_not_to_use": ["kubernetes"]},
        )
        selection = await LexicalSelector(registry).select("kubernetes")
        assert selection.is_empty


class TestFloor:
    async def test_a_query_sharing_no_vocabulary_selects_nothing(self):
        registry = await _registry(database={"description": "Apply schema migrations."})
        selection = await LexicalSelector(registry).select("photosynthesis in ferns")
        assert selection.is_empty
        assert selection.skill_ids == []

    async def test_rejects_are_still_reported(self):
        # "Ranked out" and "never registered" are different bugs that
        # look identical from inside an agent without this.
        registry = await _registry(
            database={"description": "Apply schema migrations."},
            onboarding={"description": "Onboard a new engineer."},
        )
        selection = await LexicalSelector(registry).select("photosynthesis in ferns")
        assert sorted(scored.skill_id for scored in selection.rejected) == [
            "database",
            "onboarding",
        ]
        assert selection.considered == 2

    async def test_a_raised_floor_rejects_weak_matches(self, labelled):
        selection = await LexicalSelector(labelled, min_score=1000.0).select("production incident")
        assert selection.is_empty

    async def test_an_empty_query_selects_nothing(self):
        registry = await _registry(database={"description": "Apply schema migrations."})
        assert (await LexicalSelector(registry).select("")).is_empty

    async def test_a_query_of_only_stopwords_selects_nothing(self):
        registry = await _registry(database={"description": "Apply schema migrations."})
        assert (await LexicalSelector(registry).select("what is this for")).is_empty


class TestIndexing:
    async def test_an_empty_registry_selects_nothing_without_raising(self):
        selection = await LexicalSelector(SkillRegistry()).select("anything")
        assert selection.is_empty
        assert selection.considered == 0

    async def test_a_newly_registered_skill_is_picked_up(self):
        registry = await _registry(first={"description": "Apply schema migrations."})
        selector = LexicalSelector(registry)
        await selector.select("kubernetes pods")

        await registry.register(
            "second",
            InMemorySkillProvider(
                {"second": build_skill("second", description="Debug kubernetes pods.")}
            ),
        )
        selection = await selector.select("kubernetes pods")
        assert selection.skill_ids == ["second"]

    async def test_index_can_be_built_eagerly(self):
        registry = await _registry(first={"description": "Apply schema migrations."})
        selector = LexicalSelector(registry)
        await selector.index()
        assert (await selector.select("schema migrations")).skill_ids == ["first"]


class TestLogging:
    async def test_every_selection_is_logged_with_its_scores(self, caplog):
        registry = await _registry(database={"description": "Apply schema migrations."})
        with caplog.at_level(logging.INFO, logger="agentskills.retrieval.lexical"):
            await LexicalSelector(registry).select("schema migrations")
        assert any("database" in record.message for record in caplog.records)
