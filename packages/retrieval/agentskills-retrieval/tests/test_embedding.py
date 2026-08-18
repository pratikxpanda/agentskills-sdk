"""Tests for the embedding selector, its cache, and its embedder protocol."""

from __future__ import annotations

import math

import pytest

from agentskills_core import SkillRegistry
from agentskills_retrieval import (
    EmbeddingSelector,
    InMemoryEmbeddingCache,
    cosine,
    load_embedder,
)
from agentskills_testing import InMemorySkillProvider, build_skill

VOCABULARY = ("incident", "database", "kubernetes", "onboarding", "release")


class FakeEmbedder:
    """A deterministic bag-of-vocabulary embedder.

    Real embeddings are the thing under test everywhere *except* here.
    This tests the plumbing — caching, keying, ordering, penalties —
    which is the only part of embedding selection this package owns.
    """

    embedder_id = "fake-v1"

    def __init__(self) -> None:
        self.calls = 0
        self.texts: list[str] = []

    async def embed(self, texts):
        self.calls += 1
        self.texts.extend(texts)
        return [[float(word in text.casefold()) for word in VOCABULARY] or [0.0] for text in texts]


def build_fake_embedder() -> FakeEmbedder:
    """Factory for :func:`load_embedder` tests."""
    return FakeEmbedder()


NOT_AN_EMBEDDER = object()


def build_nonsense() -> object:
    """A factory that returns something without ``embed``."""
    return NOT_AN_EMBEDDER


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
                                key: value for key, value in spec.items() if key != "description"
                            },
                        )
                    }
                ),
            )
            for skill_id, spec in skills.items()
        ]
    )
    return registry


class TestCosine:
    def test_identical_vectors_score_one(self):
        assert cosine([1.0, 2.0], [1.0, 2.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors_score_minus_one(self):
        assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_a_zero_vector_scores_zero_rather_than_dividing_by_zero(self):
        # An embedder can legitimately return zeros for empty text, and
        # a ZeroDivisionError deep in a ranking loop is a poor way to
        # find that out.
        assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
        assert cosine([1.0, 1.0], [0.0, 0.0]) == 0.0

    def test_mismatched_lengths_are_an_error_not_a_silent_truncation(self):
        with pytest.raises(ValueError):
            cosine([1.0, 0.0], [1.0])

    def test_magnitude_does_not_matter(self):
        assert cosine([1.0, 1.0], [5.0, 5.0]) == pytest.approx(1.0)
        assert not math.isnan(cosine([1e-8, 0.0], [1e-8, 0.0]))


class TestLoadEmbedder:
    def test_resolves_a_dotted_path(self):
        embedder = load_embedder(f"{__name__}:build_fake_embedder")
        assert embedder.embedder_id == "fake-v1"

    def test_a_spec_without_a_colon_is_rejected(self):
        with pytest.raises(ValueError, match="module:factory"):
            load_embedder("myapp.embedders")

    def test_an_empty_module_is_rejected(self):
        with pytest.raises(ValueError, match="module:factory"):
            load_embedder(":build")

    def test_an_unimportable_module_names_itself(self):
        with pytest.raises(ValueError, match="no_such_module_anywhere"):
            load_embedder("no_such_module_anywhere:build")

    def test_a_missing_attribute_names_itself(self):
        with pytest.raises(ValueError, match="no_such_factory"):
            load_embedder(f"{__name__}:no_such_factory")

    def test_a_factory_returning_the_wrong_shape_is_rejected(self):
        with pytest.raises(ValueError, match="embedder_id"):
            load_embedder(f"{__name__}:build_nonsense")


class TestSelection:
    async def test_the_matching_skill_wins(self):
        registry = await _registry(
            db={"description": "database work"},
            k8s={"description": "kubernetes work"},
        )
        selection = await EmbeddingSelector(registry, FakeEmbedder()).select("kubernetes")
        assert selection.skill_ids[0] == "k8s"

    async def test_nothing_similar_selects_nothing(self):
        registry = await _registry(db={"description": "database work"})
        selection = await EmbeddingSelector(registry, FakeEmbedder()).select("kubernetes")
        assert selection.is_empty
        assert [scored.skill_id for scored in selection.rejected] == ["db"]

    async def test_a_disclaimer_demotes(self):
        registry = await _registry(
            plain={"description": "kubernetes work"},
            disclaimed={"description": "kubernetes work", "when_not_to_use": ["kubernetes"]},
        )
        selection = await EmbeddingSelector(registry, FakeEmbedder()).select("kubernetes")
        assert selection.skill_ids[0] == "plain"

    async def test_the_penalty_can_be_switched_off(self):
        registry = await _registry(
            plain={"description": "kubernetes work"},
            disclaimed={"description": "kubernetes work", "when_not_to_use": ["kubernetes"]},
        )
        selector = EmbeddingSelector(registry, FakeEmbedder(), negative_weight=0.0)
        selection = await selector.select("kubernetes")
        assert [scored.score for scored in selection.selected] == pytest.approx(
            [selection.selected[0].score] * 2
        )

    async def test_ties_break_by_id(self):
        registry = await _registry(
            zebra={"description": "kubernetes work"},
            alpha={"description": "kubernetes work"},
        )
        selection = await EmbeddingSelector(registry, FakeEmbedder()).select("kubernetes")
        assert selection.skill_ids == ["alpha", "zebra"]

    async def test_limit_caps_the_result(self):
        registry = await _registry(
            **{f"skill-{i}": {"description": "kubernetes work"} for i in range(6)}
        )
        selection = await EmbeddingSelector(registry, FakeEmbedder()).select("kubernetes", limit=2)
        assert len(selection.selected) == 2

    async def test_the_floor_is_applied(self):
        registry = await _registry(db={"description": "database work"})
        selector = EmbeddingSelector(registry, FakeEmbedder(), min_score=0.99)
        assert (await selector.select("database kubernetes")).is_empty

    async def test_an_empty_registry_selects_nothing(self):
        selection = await EmbeddingSelector(SkillRegistry(), FakeEmbedder()).select("anything")
        assert selection.is_empty
        assert selection.considered == 0


class TestCaching:
    async def test_skill_vectors_are_cached_across_selections(self):
        registry = await _registry(db={"description": "database work"})
        embedder = FakeEmbedder()
        selector = EmbeddingSelector(registry, embedder)

        await selector.select("database")
        indexed = list(embedder.texts)
        await selector.select("database again")

        # The second call embeds the query only; the skill text is not
        # re-sent, which is the entire point of the content hash.
        assert embedder.texts[len(indexed) :] == ["database again"]

    async def test_a_shared_cache_survives_a_new_selector(self):
        registry = await _registry(db={"description": "database work"})
        cache = InMemoryEmbeddingCache()
        await EmbeddingSelector(registry, FakeEmbedder(), cache=cache).select("database")

        embedder = FakeEmbedder()
        await EmbeddingSelector(registry, embedder, cache=cache).select("database")
        assert embedder.texts == ["database"]

    async def test_editing_a_skill_invalidates_only_its_own_vector(self):
        cache = InMemoryEmbeddingCache()
        before = await _registry(
            db={"description": "database work"}, k8s={"description": "kubernetes work"}
        )
        await EmbeddingSelector(before, FakeEmbedder(), cache=cache).index()
        cached_before = len(cache)

        after = await _registry(
            db={"description": "database work"}, k8s={"description": "release work"}
        )
        embedder = FakeEmbedder()
        await EmbeddingSelector(after, embedder, cache=cache).index()
        assert embedder.texts == ["k8s\nrelease work"]
        assert len(cache) == cached_before + 1

    async def test_the_embedder_id_is_part_of_the_key(self):
        # Vectors from two models are not comparable; a cache that mixed
        # them would silently return nonsense rather than fail.
        registry = await _registry(db={"description": "database work"})
        cache = InMemoryEmbeddingCache()
        await EmbeddingSelector(registry, FakeEmbedder(), cache=cache).index()

        other = FakeEmbedder()
        other.embedder_id = "fake-v2"
        await EmbeddingSelector(registry, other, cache=cache).index()
        assert other.texts == ["db\ndatabase work"]
        assert len(cache) == 2

    async def test_a_newly_registered_skill_triggers_a_reindex(self):
        registry = await _registry(db={"description": "database work"})
        selector = EmbeddingSelector(registry, FakeEmbedder())
        await selector.select("kubernetes")

        await registry.register(
            "k8s",
            InMemorySkillProvider({"k8s": build_skill("k8s", description="kubernetes work")}),
        )
        assert (await selector.select("kubernetes")).skill_ids == ["k8s"]


class TestEmbedderContract:
    async def test_a_short_reply_is_an_error_rather_than_a_misalignment(self):
        # Silently zipping fewer vectors than texts would attach one
        # skill's meaning to another's ID.
        class ShortEmbedder(FakeEmbedder):
            async def embed(self, texts):
                return (await super().embed(texts))[:-1]

        registry = await _registry(
            db={"description": "database work"}, k8s={"description": "kubernetes work"}
        )
        with pytest.raises(ValueError, match="vectors"):
            await EmbeddingSelector(registry, ShortEmbedder()).index()
