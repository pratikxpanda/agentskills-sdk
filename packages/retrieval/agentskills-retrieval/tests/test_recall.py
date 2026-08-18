"""Recall over a labelled query set.

A ranker shipped without a measurement is a guess with an API.  These
floors are asserted rather than reported so that a change which makes
ranking worse fails the build instead of being noticed in production.

The corpus is small and synthetic.  These numbers are a regression
guard, not a benchmark, and the README says so.
"""

from __future__ import annotations

from agentskills_retrieval import LexicalSelector

#: Fractions of the labelled set the default selector must still get right.
MIN_RECALL_AT_1 = 0.85
MIN_RECALL_AT_3 = 1.0


async def _recall(registry, queries, k: int) -> tuple[float, list[str]]:
    selector = LexicalSelector(registry)
    misses = []
    for query, expected in queries:
        selection = await selector.select(query, limit=k)
        if expected not in selection.skill_ids[:k]:
            misses.append(f"{query!r} wanted {expected}, got {selection.skill_ids[:k]}")
    return (len(queries) - len(misses)) / len(queries), misses


class TestLexicalRecall:
    async def test_recall_at_1(self, labelled, queries):
        recall, misses = await _recall(labelled, queries, 1)
        assert recall >= MIN_RECALL_AT_1, "\n".join(misses)

    async def test_recall_at_3(self, labelled, queries):
        recall, misses = await _recall(labelled, queries, 3)
        assert recall >= MIN_RECALL_AT_3, "\n".join(misses)

    async def test_no_query_selects_nothing_at_all(self, labelled, queries):
        # A floor of zero can still reject everything, and a query that
        # returns an empty catalog is the worst outcome available.
        selector = LexicalSelector(labelled)
        empty = [query for query, _ in queries if (await selector.select(query)).is_empty]
        assert empty == []

    async def test_selection_is_stable_across_runs(self, labelled, queries):
        first = LexicalSelector(labelled)
        second = LexicalSelector(labelled)
        for query, _ in queries:
            assert (await first.select(query)).skill_ids == (await second.select(query)).skill_ids
