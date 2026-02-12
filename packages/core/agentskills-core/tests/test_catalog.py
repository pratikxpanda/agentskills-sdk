"""Tests for SkillRegistry.get_skills_catalog()."""

from unittest.mock import AsyncMock

import pytest

from agentskills_core import SkillProvider, SkillRegistry


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
