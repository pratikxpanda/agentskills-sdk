"""Tests for SkillRegistry.get_skills_catalog()."""

import logging
from unittest.mock import AsyncMock
from xml.etree.ElementTree import fromstring

import pytest

from agentskills_core import SkillNotFoundError, SkillProvider, SkillRegistry


def _mock_provider(
    skill_id: str = "incident-response",
    name: str = "incident-response",
    description: str = "Handle production incidents.",
) -> AsyncMock:
    provider = AsyncMock(spec=SkillProvider)
    provider.get_metadata.return_value = {
        "name": name,
        "description": description,
    }
    provider.get_body.return_value = "# Instructions"
    return provider


async def _make_registry(*pairs: tuple[str, AsyncMock]) -> SkillRegistry:
    registry = SkillRegistry()
    for skill_id, provider in pairs:
        await registry.register(skill_id, provider)
    return registry


class TestMarkdownFormat:
    async def test_contains_skill_name(self):
        registry = await _make_registry(("incident-response", _mock_provider()))
        prompt = await registry.get_skills_catalog(format="markdown")
        assert "incident-response" in prompt

    async def test_contains_description(self):
        registry = await _make_registry(("incident-response", _mock_provider()))
        prompt = await registry.get_skills_catalog(format="markdown")
        assert "Handle production incidents." in prompt

    async def test_empty_registry(self):
        registry = SkillRegistry()
        prompt = await registry.get_skills_catalog(format="markdown")
        assert "No skills" in prompt

    async def test_multiple_skills(self):
        p1 = _mock_provider(name="skill-a")
        p2 = _mock_provider(name="skill-b")
        registry = await _make_registry(("skill-a", p1), ("skill-b", p2))
        prompt = await registry.get_skills_catalog(format="markdown")
        assert "skill-a" in prompt
        assert "skill-b" in prompt

    async def test_has_header(self):
        registry = await _make_registry(("incident-response", _mock_provider()))
        prompt = await registry.get_skills_catalog(format="markdown")
        assert "# Available Skills" in prompt


class TestXmlFormat:
    async def test_xml_structure(self):
        registry = await _make_registry(("incident-response", _mock_provider()))
        xml = await registry.get_skills_catalog(format="xml")
        assert xml.startswith("<available_skills>")
        assert xml.endswith("</available_skills>")
        assert "<name>incident-response</name>" in xml
        assert "<description>Handle production incidents.</description>" in xml

    async def test_empty_registry(self):
        registry = SkillRegistry()
        xml = await registry.get_skills_catalog(format="xml")
        assert xml == "<available_skills />"

    async def test_multiple_skills(self):
        p1 = _mock_provider(name="skill-a")
        p2 = _mock_provider(name="skill-b")
        registry = await _make_registry(("skill-a", p1), ("skill-b", p2))
        xml = await registry.get_skills_catalog(format="xml")
        assert "<name>skill-a</name>" in xml
        assert "<name>skill-b</name>" in xml

    async def test_escapes_xml_characters(self):
        p = _mock_provider(description='Uses <brackets> & "quotes".')
        registry = await _make_registry(("incident-response", p))
        xml = await registry.get_skills_catalog(format="xml")
        assert "&lt;brackets&gt;" in xml
        assert "&amp;" in xml


class TestDefaultAndValidation:
    async def test_defaults_to_xml(self):
        registry = await _make_registry(("incident-response", _mock_provider()))
        result = await registry.get_skills_catalog()
        assert result.startswith("<available_skills>")

    async def test_invalid_format_raises(self):
        registry = await _make_registry(("incident-response", _mock_provider()))
        with pytest.raises(ValueError, match="Unsupported format"):
            await registry.get_skills_catalog(format="json")

    async def test_markdown_missing_metadata_keys(self):
        """Catalog builder handles missing name/description gracefully."""
        provider = _mock_provider(skill_id="bare-skill", name="bare-skill")
        registry = await _make_registry(("bare-skill", provider))
        # After registration passes, swap metadata to empty dict
        provider.get_metadata.return_value = {}
        prompt = await registry.get_skills_catalog(format="markdown")
        assert "bare-skill" in prompt
        assert "No description available." in prompt


class TestCatalogEdgeCases:
    """Tests for catalog edge cases: Unicode, special chars, ordering."""

    async def test_xml_with_unicode(self):
        """Unicode in skill descriptions is encoded correctly in XML."""
        p = _mock_provider(
            name="unicode-skill",
            description="\u00c9l\u00e8ve d'\u00e9cole \u2014 \u65e5\u672c\u8a9e",
        )
        registry = await _make_registry(("unicode-skill", p))
        xml = await registry.get_skills_catalog(format="xml")
        assert "unicode-skill" in xml
        assert "\u00c9l\u00e8ve" in xml
        assert "\u65e5\u672c\u8a9e" in xml

    async def test_markdown_with_special_chars(self):
        """Markdown special chars in descriptions don't break formatting."""
        p = _mock_provider(
            name="my-skill",
            description="Uses `code` and *bold* and | pipe chars.",
        )
        registry = await _make_registry(("my-skill", p))
        md = await registry.get_skills_catalog(format="markdown")
        assert "Uses `code` and *bold* and | pipe chars." in md

    async def test_large_catalog_ordering(self):
        """Many skills are returned in alphabetical order."""
        pairs = []
        for i in range(10):
            name = f"skill-{i:02d}"
            pairs.append((name, _mock_provider(name=name)))
        registry = await _make_registry(*pairs)
        xml = await registry.get_skills_catalog(format="xml")
        # Verify ordering: skill-00 appears before skill-09
        pos_first = xml.index("skill-00")
        pos_last = xml.index("skill-09")
        assert pos_first < pos_last


class TestCatalogVersion:
    """The optional ``version`` field surfaces in both catalog formats."""

    @staticmethod
    def _versioned(version: str) -> AsyncMock:
        provider = _mock_provider()
        provider.get_metadata.return_value = {
            "name": "incident-response",
            "description": "Handle production incidents.",
            "version": version,
        }
        return provider

    async def test_xml_includes_version(self):
        registry = await _make_registry(
            ("incident-response", self._versioned("1.2.3")),
        )
        xml = await registry.get_skills_catalog(format="xml")
        assert "<version>1.2.3</version>" in xml

    async def test_markdown_includes_version(self):
        registry = await _make_registry(
            ("incident-response", self._versioned("1.2.3")),
        )
        md = await registry.get_skills_catalog(format="markdown")
        assert "- **Version**: 1.2.3" in md

    async def test_xml_omits_version_when_absent(self):
        registry = await _make_registry(("incident-response", _mock_provider()))
        xml = await registry.get_skills_catalog(format="xml")
        assert "<version>" not in xml

    async def test_markdown_omits_version_when_absent(self):
        registry = await _make_registry(("incident-response", _mock_provider()))
        md = await registry.get_skills_catalog(format="markdown")
        assert "**Version**" not in md


def _tagged(name: str, tags: object) -> AsyncMock:
    provider = _mock_provider(name=name)
    provider.get_metadata.return_value = {
        "name": name,
        "description": f"Does {name}.",
        "metadata": {"tags": tags},
    }
    return provider


async def _three_skills() -> SkillRegistry:
    return await _make_registry(
        ("skill-a", _mock_provider(name="skill-a")),
        ("skill-b", _mock_provider(name="skill-b")),
        ("skill-c", _mock_provider(name="skill-c")),
    )


class TestIdFilters:
    """``include`` and ``exclude`` narrow the catalog by skill ID."""

    async def test_include_keeps_only_the_named_skills(self):
        registry = await _three_skills()
        xml = await registry.get_skills_catalog(include=["skill-a", "skill-c"])
        assert "skill-a" in xml
        assert "skill-c" in xml
        assert "skill-b" not in xml

    async def test_include_naming_an_unregistered_skill_raises(self):
        registry = await _three_skills()
        with pytest.raises(SkillNotFoundError, match="skill-z"):
            await registry.get_skills_catalog(include=["skill-a", "skill-z"])

    async def test_exclude_drops_the_named_skills(self):
        registry = await _three_skills()
        xml = await registry.get_skills_catalog(exclude=["skill-b"])
        assert "skill-a" in xml
        assert "skill-b" not in xml

    async def test_exclude_wins_over_include(self):
        registry = await _three_skills()
        xml = await registry.get_skills_catalog(include=["skill-a"], exclude=["skill-a"])
        assert "skill-a" not in xml

    async def test_exclude_tolerates_unregistered_ids(self):
        """A deny-list is meant to outlive the thing it denies."""
        registry = await _three_skills()
        xml = await registry.get_skills_catalog(exclude=["retired-last-year"])
        assert "skill-a" in xml

    async def test_id_filters_run_before_any_metadata_is_fetched(self):
        dropped = _mock_provider(name="skill-b")
        registry = await _make_registry(
            ("skill-a", _mock_provider(name="skill-a")),
            ("skill-b", dropped),
        )
        dropped.get_metadata.reset_mock()  # registration validated it already

        await registry.get_skills_catalog(exclude=["skill-b"])

        dropped.get_metadata.assert_not_awaited()

    async def test_filtering_everything_out_yields_an_empty_catalog(self):
        registry = await _three_skills()
        xml = await registry.get_skills_catalog(exclude=["skill-a", "skill-b", "skill-c"])
        assert xml == "<available_skills />"


class TestTagFilter:
    """``tags`` reads the spec's free-form ``metadata`` mapping."""

    async def test_matches_any_of_the_requested_tags(self):
        registry = await _make_registry(
            ("skill-a", _tagged("skill-a", ["incident", "sev1"])),
            ("skill-b", _tagged("skill-b", ["billing"])),
        )
        xml = await registry.get_skills_catalog(tags=["incident", "onboarding"])
        assert "skill-a" in xml
        assert "skill-b" not in xml

    async def test_matching_is_case_insensitive(self):
        registry = await _make_registry(("skill-a", _tagged("skill-a", ["Incident"])))
        xml = await registry.get_skills_catalog(tags=["INCIDENT"])
        assert "skill-a" in xml

    async def test_an_untagged_skill_matches_no_tag_filter(self):
        registry = await _make_registry(("skill-a", _mock_provider(name="skill-a")))
        xml = await registry.get_skills_catalog(tags=["incident"])
        assert xml == "<available_skills />"

    async def test_an_empty_tag_list_allows_nothing(self):
        registry = await _make_registry(("skill-a", _tagged("skill-a", ["incident"])))
        xml = await registry.get_skills_catalog(tags=[])
        assert xml == "<available_skills />"

    async def test_a_malformed_tags_value_is_ignored_and_warned_about(self, caplog):
        registry = await _make_registry(("skill-a", _tagged("skill-a", "incident")))
        with caplog.at_level(logging.WARNING, logger="agentskills.core.registry"):
            xml = await registry.get_skills_catalog(tags=["incident"])
        assert xml == "<available_skills />"
        assert "metadata.tags must be a list of strings" in caplog.text

    async def test_tags_outside_the_metadata_mapping_are_not_read(self):
        """A top-level ``tags`` field would be a spec fork; it is not one."""
        provider = _mock_provider(name="skill-a")
        provider.get_metadata.return_value = {
            "name": "skill-a",
            "description": "Does skill-a.",
            "tags": ["incident"],
        }
        registry = await _make_registry(("skill-a", provider))
        xml = await registry.get_skills_catalog(tags=["incident"])
        assert xml == "<available_skills />"

    async def test_a_metadata_mapping_without_tags_matches_nothing(self):
        provider = _mock_provider(name="skill-a")
        provider.get_metadata.return_value = {
            "name": "skill-a",
            "description": "Does skill-a.",
            "metadata": {"owner": "sre"},
        }
        registry = await _make_registry(("skill-a", provider))
        assert await registry.get_skills_catalog(tags=["incident"]) == "<available_skills />"

    async def test_combines_with_the_id_filters(self):
        registry = await _make_registry(
            ("skill-a", _tagged("skill-a", ["incident"])),
            ("skill-b", _tagged("skill-b", ["incident"])),
        )
        xml = await registry.get_skills_catalog(tags=["incident"], exclude=["skill-b"])
        assert "skill-a" in xml
        assert "skill-b" not in xml


class TestMaxChars:
    """``max_chars`` is a hard ceiling, and truncation is never silent."""

    @staticmethod
    async def _ten_skills() -> SkillRegistry:
        return await _make_registry(
            *((f"skill-{i:02d}", _mock_provider(name=f"skill-{i:02d}")) for i in range(10))
        )

    async def test_a_generous_budget_changes_nothing(self):
        registry = await self._ten_skills()
        unbounded = await registry.get_skills_catalog()
        assert await registry.get_skills_catalog(max_chars=100_000) == unbounded

    async def test_the_ceiling_is_respected(self):
        registry = await self._ten_skills()
        xml = await registry.get_skills_catalog(max_chars=400)
        assert len(xml) <= 400

    async def test_whole_entries_are_dropped_from_the_end(self):
        registry = await self._ten_skills()
        xml = await registry.get_skills_catalog(max_chars=400)
        root = fromstring(xml)
        names = [el.findtext("name") for el in root.findall("skill")]
        assert names == sorted(names)
        assert names == [f"skill-{i:02d}" for i in range(len(names))]

    async def test_xml_reports_what_it_dropped(self):
        registry = await self._ten_skills()
        root = fromstring(await registry.get_skills_catalog(max_chars=400))
        assert root.get("truncated") == "true"
        assert root.get("total") == "10"
        assert root.get("shown") == str(len(root.findall("skill")))

    async def test_untruncated_xml_carries_no_attributes(self):
        registry = await self._ten_skills()
        root = fromstring(await registry.get_skills_catalog())
        assert root.attrib == {}

    async def test_markdown_says_it_was_truncated(self):
        registry = await self._ten_skills()
        md = await registry.get_skills_catalog(format="markdown", max_chars=400)
        assert len(md) <= 400
        assert "_Catalog truncated: showing" in md
        assert "of 10 skills._" in md

    async def test_truncation_is_deterministic(self):
        registry = await self._ten_skills()
        first = await registry.get_skills_catalog(max_chars=400)
        second = await registry.get_skills_catalog(max_chars=400)
        assert first == second

    async def test_a_budget_that_fits_nothing_still_reports_the_total(self):
        registry = await self._ten_skills()
        root = fromstring(await registry.get_skills_catalog(max_chars=70))
        assert root.findall("skill") == []
        assert root.get("total") == "10"

    async def test_an_impossible_budget_raises(self):
        registry = await self._ten_skills()
        with pytest.raises(ValueError, match="cannot hold the smallest possible catalog"):
            await registry.get_skills_catalog(max_chars=5)

    async def test_markdown_truncated_to_nothing_still_reports_the_total(self):
        registry = await self._ten_skills()
        md = await registry.get_skills_catalog(format="markdown", max_chars=90)
        assert md.startswith("No skills are currently available.")
        assert "showing 0 of 10 skills._" in md

    async def test_an_empty_registry_needs_no_truncation(self):
        registry = SkillRegistry()
        assert await registry.get_skills_catalog(max_chars=100) == "<available_skills />"


class TestCatalogConcurrency:
    async def test_must_be_at_least_one(self):
        with pytest.raises(ValueError, match="catalog_concurrency must be at least 1"):
            SkillRegistry(catalog_concurrency=0)

    async def test_a_provider_failure_names_the_skill_it_came_from(self):
        provider = _mock_provider(name="skill-a")
        registry = await _make_registry(("skill-a", provider))
        provider.get_metadata.side_effect = RuntimeError("backend on fire")

        with pytest.raises(RuntimeError) as excinfo:
            await registry.get_skills_catalog()

        assert any("skill-a" in note for note in excinfo.value.__notes__)
