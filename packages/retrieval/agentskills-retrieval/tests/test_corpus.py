"""Tests for the searchable document a skill is reduced to."""

from __future__ import annotations

from agentskills_core import SkillRegistry
from agentskills_retrieval import STOPWORDS, build_corpus, document_of, tokenize
from agentskills_testing import InMemorySkillProvider, build_skill


class TestTokenize:
    def test_splits_on_anything_that_is_not_alphanumeric(self):
        assert tokenize("deploy-to_prod (v2)") == ["deploy", "prod", "v2"]

    def test_is_case_insensitive(self):
        assert tokenize("Kubernetes") == tokenize("KUBERNETES") == ["kubernetes"]

    def test_drops_stopwords(self):
        assert tokenize("how to use the thing") == ["thing"]

    def test_keeps_a_stopword_bearing_query_from_becoming_empty_words(self):
        # Every term here is a stopword; the caller gets nothing rather
        # than a match against every skill in the registry.
        assert tokenize("what is this for") == []

    def test_the_stopword_list_stays_small_enough_to_read(self):
        # A long list is an unmaintained language model.  If this fails,
        # the fix is to delete words, not to raise the number.
        assert len(STOPWORDS) < 60

    def test_empty_text_is_no_terms(self):
        assert tokenize("") == []


class TestDocumentOf:
    def test_positive_text_carries_name_description_and_when_to_use(self):
        document = document_of(
            "incident-response",
            {
                "name": "incident-response",
                "description": "Mitigate outages.",
                "when_to_use": ["A service is down"],
            },
        )
        assert "incident-response" in document.positive_text
        assert "Mitigate outages." in document.positive_text
        assert "A service is down" in document.positive_text

    def test_when_not_to_use_is_kept_out_of_the_positive_text(self):
        document = document_of(
            "incident-response",
            {"description": "Mitigate outages.", "when_not_to_use": ["A local test failure"]},
        )
        assert "local test failure" not in document.positive_text.casefold()
        assert "A local test failure" in document.negative_text

    def test_tags_are_indexed(self):
        document = document_of(
            "incident-response",
            {"description": "Mitigate outages.", "metadata": {"tags": ["oncall", "sev1"]}},
        )
        assert "oncall" in document.positive_terms
        assert "sev1" in document.positive_terms

    def test_the_skill_id_stands_in_for_a_missing_name(self):
        document = document_of("release-process", {"description": "Ship it."})
        assert "release-process" in document.positive_text

    def test_malformed_selection_fields_are_ignored_rather_than_raising(self):
        # Metadata comes from a file someone hand-wrote; a string where a
        # list belongs should cost that skill its keywords, not the run.
        document = document_of(
            "broken",
            {"description": "Ship it.", "when_to_use": "not a list", "when_not_to_use": 7},
        )
        assert "not a list" not in document.positive_text
        assert document.negative_text == ""

    def test_non_string_entries_inside_a_list_are_dropped(self):
        document = document_of("broken", {"description": "d", "when_to_use": ["ok", 3, None, "  "]})
        assert "ok" in document.positive_text
        assert "None" not in document.positive_text


class TestContentHash:
    def test_identical_metadata_hashes_identically(self):
        meta = {"description": "Mitigate outages.", "when_to_use": ["down"]}
        assert (
            document_of("a", dict(meta)).content_hash == document_of("a", dict(meta)).content_hash
        )

    def test_a_changed_description_invalidates_the_hash(self):
        before = document_of("a", {"description": "Mitigate outages."})
        after = document_of("a", {"description": "Mitigate outages fast."})
        assert before.content_hash != after.content_hash

    def test_a_changed_disclaimer_invalidates_the_hash(self):
        before = document_of("a", {"description": "d", "when_not_to_use": ["x"]})
        after = document_of("a", {"description": "d", "when_not_to_use": ["y"]})
        assert before.content_hash != after.content_hash

    def test_moving_text_between_the_halves_changes_the_hash(self):
        # Without a separator in the digest these two would collide, and
        # a cached vector would be served for the opposite meaning.
        positive_only = document_of("a", {"name": "a", "description": "x\ny"})
        split = document_of("a", {"name": "a", "description": "x", "when_not_to_use": ["y"]})
        assert positive_only.content_hash != split.content_hash

    def test_the_skill_id_alone_does_not_change_the_hash(self):
        # The hash keys a vector for some *text*; two skills with
        # identical text should share it.
        left = document_of("a", {"name": "shared", "description": "d"})
        right = document_of("b", {"name": "shared", "description": "d"})
        assert left.content_hash == right.content_hash


class TestBuildCorpus:
    async def test_indexes_every_registered_skill(self):
        registry = SkillRegistry()
        await registry.register(
            [
                ("first", InMemorySkillProvider({"first": build_skill("first")})),
                ("second", InMemorySkillProvider({"second": build_skill("second")})),
            ]
        )
        corpus = await build_corpus(registry)
        assert [document.skill_id for document in corpus] == ["first", "second"]

    async def test_an_empty_registry_yields_an_empty_corpus(self):
        assert await build_corpus(SkillRegistry()) == []

    async def test_concurrency_is_bounded(self):
        registry = SkillRegistry()
        await registry.register(
            [
                (
                    f"skill-{index}",
                    InMemorySkillProvider({f"skill-{index}": build_skill(f"skill-{index}")}),
                )
                for index in range(12)
            ]
        )
        corpus = await build_corpus(registry, concurrency=2)
        assert len(corpus) == 12
