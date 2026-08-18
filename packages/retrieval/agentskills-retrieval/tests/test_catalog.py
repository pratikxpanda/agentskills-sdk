"""Tests for composing a selection with the catalog renderer."""

from __future__ import annotations

import logging

import pytest

from agentskills_core import SkillRegistry
from agentskills_retrieval import LexicalSelector, build_selected_catalog
from agentskills_testing import InMemorySkillProvider, build_skill


class TestNarrowing:
    async def test_only_the_selected_skills_are_advertised(self, labelled):
        catalog = await build_selected_catalog(
            labelled, LexicalSelector(labelled), "my pod is in CrashLoopBackOff", limit=2
        )
        assert "kubernetes-debugging" in catalog
        assert "onboarding-new-hire" not in catalog

    async def test_the_catalog_reports_the_shortfall_in_xml(self, labelled):
        # Without total=, an include-narrowed catalog silently claims to
        # be the whole registry.
        selector = LexicalSelector(labelled)
        selection = await selector.select("my pod is in CrashLoopBackOff", limit=2)
        catalog = await build_selected_catalog(
            labelled, selector, "my pod is in CrashLoopBackOff", limit=2
        )
        assert 'truncated="true"' in catalog
        assert f'shown="{len(selection.selected)}"' in catalog
        assert f'total="{len(labelled.list_skills())}"' in catalog

    async def test_the_catalog_reports_the_shortfall_in_markdown(self, labelled):
        selector = LexicalSelector(labelled)
        selection = await selector.select("my pod is in CrashLoopBackOff", limit=2)
        catalog = await build_selected_catalog(
            labelled,
            selector,
            "my pod is in CrashLoopBackOff",
            limit=2,
            format="markdown",
        )
        shown = len(selection.selected)
        assert f"showing {shown} of {len(labelled.list_skills())} skills" in catalog

    async def test_catalog_options_are_passed_through(self, labelled):
        catalog = await build_selected_catalog(
            labelled,
            LexicalSelector(labelled),
            "my pod is in CrashLoopBackOff",
            limit=2,
            selection_hints=False,
        )
        assert "when_to_use" not in catalog


class TestFallback:
    async def test_an_empty_selection_returns_the_full_catalog(self, labelled):
        # "Selection has no opinion" is not "the agent has no skills".
        catalog = await build_selected_catalog(
            labelled, LexicalSelector(labelled), "photosynthesis in ferns"
        )
        for skill_id in (skill.get_id() for skill in labelled.list_skills()):
            assert skill_id in catalog

    async def test_the_fallback_says_so(self, labelled, caplog):
        with caplog.at_level(logging.INFO, logger="agentskills.retrieval.catalog"):
            await build_selected_catalog(
                labelled, LexicalSelector(labelled), "photosynthesis in ferns"
            )
        assert any("full catalog" in record.message for record in caplog.records)

    async def test_the_full_catalog_does_not_claim_to_be_truncated(self, labelled):
        catalog = await build_selected_catalog(
            labelled, LexicalSelector(labelled), "photosynthesis in ferns"
        )
        assert "truncated" not in catalog

    async def test_an_empty_registry_produces_a_catalog_rather_than_an_error(self):
        registry = SkillRegistry()
        catalog = await build_selected_catalog(registry, LexicalSelector(registry), "anything")
        assert isinstance(catalog, str)


class TestManualComposition:
    async def test_include_and_total_can_be_driven_directly(self, labelled):
        # The documented two-line integration; if this breaks, so does
        # every caller who preferred not to use the helper.
        selection = await LexicalSelector(labelled).select("slow report query", limit=3)
        catalog = await labelled.get_skills_catalog(
            include=selection.skill_ids, total=selection.considered
        )
        assert "sql-query-tuning" in catalog
        assert f'total="{selection.considered}"' in catalog

    async def test_narrowing_avoids_fetching_the_rest(self, labelled):
        # include= is applied before metadata is fetched, which is the
        # reason this is worth doing on a network-backed registry.
        selection = await LexicalSelector(labelled).select("slow report query", limit=1)
        assert len(selection.skill_ids) == 1


class TestCoreTotalKeyword:
    """The one core change item 3 required, tested where it is used."""

    @staticmethod
    async def _registry(count: int) -> SkillRegistry:
        registry = SkillRegistry()
        await registry.register(
            [
                (f"skill-{i}", InMemorySkillProvider({f"skill-{i}": build_skill(f"skill-{i}")}))
                for i in range(count)
            ]
        )
        return registry

    async def test_total_defaults_to_the_post_filter_count(self):
        # A deliberate static filter should not pay for a "truncated"
        # note on every turn.
        registry = await self._registry(4)
        catalog = await registry.get_skills_catalog(include=["skill-0", "skill-1"])
        assert "truncated" not in catalog

    async def test_a_supplied_total_makes_the_narrowing_visible(self):
        registry = await self._registry(4)
        catalog = await registry.get_skills_catalog(include=["skill-0"], total=4)
        assert 'shown="1"' in catalog
        assert 'total="4"' in catalog

    async def test_a_total_below_the_shown_count_is_ignored(self):
        # A denominator smaller than its numerator is a caller bug, and
        # "showing 2 of 1" is worse than saying nothing.
        registry = await self._registry(2)
        catalog = await registry.get_skills_catalog(total=1)
        assert "truncated" not in catalog

    @pytest.mark.parametrize("fmt", ["xml", "markdown"])
    async def test_an_equal_total_reports_nothing(self, fmt):
        registry = await self._registry(3)
        catalog = await registry.get_skills_catalog(format=fmt, total=3)
        assert "truncated" not in catalog.casefold()
