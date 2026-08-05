"""Tests for token cost reporting."""

from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pytest

from agentskills_cli.cost import (
    HEURISTIC,
    PREAMBLE_TITLE,
    ResourceCost,
    SectionCost,
    SkillCost,
    TokenCounter,
    cost_exit_code,
    cost_payload,
    cost_skill,
    over_budget,
    render_cost_text,
    resolve_counter,
    split_sections,
)
from agentskills_cli.discovery import CliError
from agentskills_core import Skill
from agentskills_fs import LocalFileSystemSkillProvider

WORDS = TokenCounter("words", True, lambda text: len(text.split()))


def _cost(**overrides) -> SkillCost:
    defaults = {
        "skill_id": "alpha",
        "path": "skills/alpha",
        "counter": WORDS,
        "catalog_tokens": 100,
        "body_tokens": 900,
        "sections": [],
        "resources": [],
    }
    return SkillCost(**{**defaults, **overrides})


class TestSplitSections:
    def test_text_with_no_headings_is_one_preamble(self):
        [section] = split_sections("just prose\nover two lines")

        assert section.title == PREAMBLE_TITLE
        assert section.level == 0

    def test_empty_body_produces_nothing(self):
        assert split_sections("") == []

    def test_whitespace_before_a_heading_is_not_a_section(self):
        [section] = split_sections("\n\n# Title\n\nbody")

        assert section.title == "Title"

    def test_headings_become_sections_in_order(self):
        sections = split_sections("# One\n\na\n\n## Two\n\nb\n\n## Three\n\nc")

        assert [(s.title, s.level) for s in sections] == [("One", 1), ("Two", 2), ("Three", 2)]

    def test_a_nested_section_is_not_also_counted_in_its_parent(self):
        body = "## Parent\n\nparent text\n\n### Child\n\nchild text"
        parent, child = split_sections(body)

        assert "child text" not in parent.text
        assert "child text" in child.text

    def test_the_parts_sum_to_the_whole(self):
        body = "intro\n\n# One\n\na\n\n## Two\n\nb\n"
        sections = split_sections(body)

        # Rejoining is exact except for the trailing newline splitlines drops.
        assert "\n".join(section.text for section in sections) == body.rstrip("\n")

    def test_a_hash_inside_a_fence_is_a_comment_not_a_heading(self):
        body = "# Real\n\n```bash\n# not a heading\necho hi\n```\n\ntail"
        [section] = split_sections(body)

        assert section.title == "Real"
        assert "not a heading" in section.text

    def test_tilde_fences_are_honoured_too(self):
        body = "# Real\n\n~~~\n# not a heading\n~~~\n"
        [section] = split_sections(body)

        assert section.title == "Real"

    def test_a_fence_of_a_different_character_does_not_close_one(self):
        body = "# Real\n\n```\n~~~\n# still inside\n```\n\n# After"
        real, after = split_sections(body)

        assert "still inside" in real.text
        assert after.title == "After"

    def test_closing_hashes_are_stripped_from_the_title(self):
        [section] = split_sections("## Title ##\n\nbody")

        assert section.title == "Title"

    def test_a_hash_without_a_space_is_not_a_heading(self):
        [section] = split_sections("#hashtag\n\nbody")

        assert section.title == PREAMBLE_TITLE

    def test_seven_hashes_are_not_a_heading(self):
        [section] = split_sections("####### too deep\n\nbody")

        assert section.title == PREAMBLE_TITLE

    def test_an_empty_section_still_counts(self):
        # A heading with nothing under it still charges for its own line.
        sections = split_sections("# One\n# Two\n")

        assert [s.title for s in sections] == ["One", "Two"]


class TestResolveCounter:
    @pytest.fixture
    def without_tiktoken(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "tiktoken", None)

    @pytest.fixture
    def with_tiktoken(self, monkeypatch):
        module = types.ModuleType("tiktoken")

        class _Encoding:
            def encode(self, text: str) -> list[int]:
                return list(range(len(text.split())))

        module.get_encoding = lambda name: _Encoding()
        monkeypatch.setitem(sys.modules, "tiktoken", module)
        return module

    def test_heuristic_is_returned_verbatim(self):
        assert resolve_counter("heuristic") is HEURISTIC

    def test_auto_falls_back_when_tiktoken_is_absent(self, without_tiktoken):
        counter = resolve_counter("auto")

        assert counter is HEURISTIC
        assert counter.exact is False

    def test_auto_prefers_tiktoken_when_it_is_there(self, with_tiktoken):
        counter = resolve_counter("auto")

        assert counter.name.startswith("tiktoken/")
        assert counter.exact is True
        assert counter.count("one two three") == 3

    def test_demanding_tiktoken_fails_loudly_when_it_is_absent(self, without_tiktoken):
        with pytest.raises(CliError, match="--tokenizer heuristic"):
            resolve_counter("tiktoken")

    def test_an_unloadable_vocabulary_is_a_fallback_not_a_crash(self, with_tiktoken):
        def explode(name: str) -> None:
            raise RuntimeError("no network")

        with_tiktoken.get_encoding = explode

        assert resolve_counter("auto") is HEURISTIC

    def test_an_unloadable_vocabulary_still_fails_when_demanded(self, with_tiktoken):
        def explode(name: str) -> None:
            raise RuntimeError("no network")

        with_tiktoken.get_encoding = explode

        with pytest.raises(CliError, match="vocabulary"):
            resolve_counter("tiktoken")

    def test_the_heuristic_is_four_characters_a_token(self):
        assert HEURISTIC.count("x" * 40) == 10


class TestCostSkill:
    async def _cost(self, root: Path, skill_id: str = "alpha") -> SkillCost:
        skill = Skill(skill_id, LocalFileSystemSkillProvider(root))
        body = await skill.get_body()
        return await cost_skill(skill, f"skills/{skill_id}", "<catalog/>", body, WORDS)

    async def test_sections_sum_to_the_body(self, write_skill, skills_root):
        write_skill(
            "alpha",
            "---\nname: alpha\ndescription: d\n---\n\n# One\n\nalpha beta\n\n## Two\n\ngamma\n",
        )

        cost = await self._cost(skills_root)

        assert sum(section.tokens for section in cost.sections) == cost.body_tokens

    async def test_a_text_resource_is_counted(self, write_skill, skills_root):
        path = write_skill("alpha")
        (path / "references").mkdir()
        (path / "references" / "api.md").write_text("one two three", encoding="utf-8")

        cost = await self._cost(skills_root)

        [resource] = cost.resources
        assert (resource.kind, resource.name, resource.tokens) == ("references", "api.md", 3)

    async def test_a_binary_resource_has_a_size_but_no_token_count(self, write_skill, skills_root):
        path = write_skill("alpha")
        (path / "assets").mkdir()
        (path / "assets" / "logo.png").write_bytes(b"\x89PNG\xff\xfe")

        cost = await self._cost(skills_root)

        [resource] = cost.resources
        assert resource.tokens is None
        assert resource.size == 6

    async def test_resources_are_grouped_by_kind_in_spec_order(self, write_skill, skills_root):
        path = write_skill("alpha")
        for kind in ("references", "scripts", "assets"):
            (path / kind).mkdir()
            (path / kind / "f.txt").write_text("x", encoding="utf-8")

        cost = await self._cost(skills_root)

        assert [r.kind for r in cost.resources] == ["references", "scripts", "assets"]

    async def test_a_provider_without_listing_reports_no_resources(
        self, write_skill, skills_root, monkeypatch
    ):
        write_skill("alpha")
        monkeypatch.setattr(
            LocalFileSystemSkillProvider, "supports_resource_listing", False, raising=False
        )

        cost = await self._cost(skills_root)

        assert cost.resources == []


class TestTotals:
    def test_per_turn_is_the_catalog_entry_alone(self):
        assert _cost().per_turn == 100

    def test_per_load_adds_the_body(self):
        assert _cost().per_load == 1000

    def test_on_demand_ignores_uncountable_resources(self):
        cost = _cost(
            resources=[
                ResourceCost("references", "a.md", 10, 7),
                ResourceCost("assets", "b.png", 999, None),
            ]
        )

        assert cost.on_demand == 7


class TestBudgets:
    def test_nothing_is_breached_without_budgets(self):
        assert over_budget(_cost(), budget=None, turn_budget=None) == []

    def test_the_turn_budget_gates_the_catalog_entry(self):
        [breach] = over_budget(_cost(), budget=None, turn_budget=50)

        assert "per-turn cost is 100 tokens" in breach

    def test_the_load_budget_gates_catalog_plus_body(self):
        [breach] = over_budget(_cost(), budget=500, turn_budget=None)

        assert "per-load cost is 1000 tokens" in breach

    def test_a_budget_met_exactly_is_not_a_breach(self):
        assert over_budget(_cost(), budget=1000, turn_budget=100) == []

    def test_both_can_breach_at_once(self):
        assert len(over_budget(_cost(), budget=1, turn_budget=1)) == 2

    def test_exit_code_is_one_when_any_skill_breaches(self):
        costs = [_cost(), _cost(skill_id="beta", catalog_tokens=9000)]

        assert cost_exit_code(costs, budget=None, turn_budget=100) == 1
        assert cost_exit_code(costs, budget=None, turn_budget=None) == 0


class TestRenderText:
    def _render(self, costs, **budgets) -> str:
        out = io.StringIO()
        render_cost_text(costs, out, **budgets)
        return out.getvalue()

    def test_the_two_charges_are_labelled_by_when_they_apply(self):
        text = self._render([_cost()])

        assert "catalog entry" in text
        assert "every turn" in text
        assert "body" in text
        assert "on load" in text

    def test_the_counter_is_always_named(self):
        assert "counted with words" in self._render([_cost()])

    def test_a_heuristic_count_is_marked_estimated(self):
        assert "estimated" in self._render([_cost(counter=HEURISTIC)])

    def test_an_exact_count_is_not(self):
        assert "estimated" not in self._render([_cost()])

    def test_sections_are_indented_by_depth(self):
        text = self._render(
            [_cost(sections=[SectionCost("Top", 1, 10), SectionCost("Nested", 3, 5)])]
        )

        assert "    Top" in text
        assert "        Nested" in text

    def test_amounts_are_right_aligned_in_one_column(self):
        cost = _cost(sections=[SectionCost("A section with a very long title", 1, 5)])
        rows = [
            line
            for line in self._render([cost]).splitlines()
            if line.startswith(("  catalog entry", "  body", "    A section"))
        ]
        ends = {len(line.removesuffix("  every turn").removesuffix("  on load")) for line in rows}

        assert len(rows) == 3
        assert len(ends) == 1

    def test_large_numbers_are_grouped(self):
        assert "1,234" in self._render([_cost(body_tokens=1234)])

    def test_a_binary_resource_reports_bytes(self):
        text = self._render([_cost(resources=[ResourceCost("assets", "l.png", 2048, None)])])

        assert "bytes, not text" in text
        assert "2,048" in text

    def test_a_text_resource_is_charged_on_demand(self):
        text = self._render([_cost(resources=[ResourceCost("references", "api.md", 40, 12)])])

        assert "references/api.md" in text
        assert "12  on demand" in text

    def test_breaches_are_printed_under_the_skill(self):
        text = self._render([_cost()], budget=1, turn_budget=None)

        assert "over budget: per-load cost is 1000 tokens" in text

    def test_multiple_skills_are_separated(self):
        text = self._render([_cost(), _cost(skill_id="beta")])

        assert "\n\nskills/alpha" in text

    def test_the_summary_totals_only_the_per_turn_cost(self):
        text = self._render([_cost(), _cost(skill_id="beta")])

        # Per-load cost is only paid by the skills an agent actually
        # loads; per-turn is paid for all of them, always.
        assert "2 skills, 200 tokens charged every turn" in text

    def test_one_skill_is_singular(self):
        assert "1 skill, 100 tokens" in self._render([_cost()])


class TestPayload:
    def test_it_is_serialisable_and_carries_the_counter(self):
        [entry] = cost_payload([_cost()], budget=None, turn_budget=None)

        assert json.dumps(entry)
        assert entry["counter"] == {"name": "words", "exact": True}
        assert entry["perTurn"] == 100
        assert entry["perLoad"] == 1000

    def test_sections_and_resources_are_included(self):
        cost = _cost(
            sections=[SectionCost("S", 2, 5)],
            resources=[ResourceCost("assets", "l.png", 9, None)],
        )

        [entry] = cost_payload([cost], budget=None, turn_budget=None)

        assert entry["sections"] == [{"title": "S", "level": 2, "tokens": 5}]
        assert entry["resources"] == [
            {"kind": "assets", "name": "l.png", "bytes": 9, "tokens": None}
        ]

    def test_breaches_travel_in_the_payload(self):
        [entry] = cost_payload([_cost()], budget=1, turn_budget=None)

        assert len(entry["overBudget"]) == 1
