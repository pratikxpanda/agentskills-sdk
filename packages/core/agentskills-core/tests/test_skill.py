"""Tests for Skill — verifies delegation to provider."""

from unittest.mock import AsyncMock

import pytest

from agentskills_core import Skill, SkillProvider


def _make_mock_provider() -> AsyncMock:
    """Create a mock provider with standard return values."""
    provider = AsyncMock(spec=SkillProvider)
    provider.get_metadata.return_value = {
        "name": "incident-response",
        "description": "Handle production incidents.",
    }
    provider.get_body.return_value = "# Incident Response\nHandle incidents."
    provider.get_script.return_value = b"#!/bin/bash\necho paging"
    provider.get_asset.return_value = b"graph TD; A-->B"
    provider.get_reference.return_value = b"# Severity Levels"
    return provider


class TestSkill:
    def test_skill_id(self):
        provider = _make_mock_provider()
        skill = Skill("incident-response", provider)
        assert skill.get_id() == "incident-response"

    async def test_metadata_delegates(self):
        provider = _make_mock_provider()
        skill = Skill("incident-response", provider)
        meta = await skill.get_metadata()
        provider.get_metadata.assert_called_once_with("incident-response")
        assert meta["name"] == "incident-response"

    async def test_body_delegates(self):
        provider = _make_mock_provider()
        skill = Skill("incident-response", provider)
        body = await skill.get_body()
        provider.get_body.assert_called_once_with("incident-response")
        assert "Incident Response" in body

    async def test_get_script_delegates(self):
        provider = _make_mock_provider()
        skill = Skill("incident-response", provider)
        data = await skill.get_script("page-oncall.sh")
        provider.get_script.assert_called_once_with("incident-response", "page-oncall.sh")
        assert data == b"#!/bin/bash\necho paging"

    async def test_get_asset_delegates(self):
        provider = _make_mock_provider()
        skill = Skill("incident-response", provider)
        data = await skill.get_asset("flowchart.mermaid")
        provider.get_asset.assert_called_once_with("incident-response", "flowchart.mermaid")
        assert data == b"graph TD; A-->B"

    async def test_get_reference_delegates(self):
        provider = _make_mock_provider()
        skill = Skill("incident-response", provider)
        data = await skill.get_reference("severity-levels.md")
        provider.get_reference.assert_called_once_with("incident-response", "severity-levels.md")
        assert data == b"# Severity Levels"

    def test_repr(self):
        provider = _make_mock_provider()
        skill = Skill("incident-response", provider)
        assert repr(skill) == "Skill('incident-response')"


class TestSkillGuardClauses:
    def test_rejects_empty_skill_id(self):
        with pytest.raises(ValueError, match="non-empty string"):
            Skill("", _make_mock_provider())

    def test_rejects_whitespace_only_skill_id(self):
        with pytest.raises(ValueError, match="non-empty string"):
            Skill("   ", _make_mock_provider())

    def test_rejects_non_string_skill_id(self):
        with pytest.raises(ValueError, match="non-empty string"):
            Skill(123, _make_mock_provider())  # type: ignore[arg-type]

    def test_rejects_non_provider(self):
        with pytest.raises(TypeError, match="SkillProvider"):
            Skill("my-skill", "not-a-provider")  # type: ignore[arg-type]

    def test_rejects_none_provider(self):
        with pytest.raises(TypeError, match="SkillProvider"):
            Skill("my-skill", None)  # type: ignore[arg-type]


class TestSkillErrorPropagation:
    """Tests for error propagation through Skill delegation."""

    def test_rejects_none_skill_id(self):
        """None skill_id hits the non-string guard."""
        with pytest.raises(ValueError, match="non-empty string"):
            Skill(None, _make_mock_provider())  # type: ignore[arg-type]

    async def test_provider_exception_propagates(self):
        """Exceptions from provider methods propagate through Skill."""
        provider = _make_mock_provider()
        provider.get_body.side_effect = RuntimeError("network fail")
        skill = Skill("incident-response", provider)
        with pytest.raises(RuntimeError, match="network fail"):
            await skill.get_body()

    async def test_provider_exception_on_metadata(self):
        """Exception from get_metadata propagates correctly."""
        from agentskills_core import SkillNotFoundError

        provider = _make_mock_provider()
        provider.get_metadata.side_effect = SkillNotFoundError("not found")
        skill = Skill("incident-response", provider)
        with pytest.raises(SkillNotFoundError, match="not found"):
            await skill.get_metadata()
