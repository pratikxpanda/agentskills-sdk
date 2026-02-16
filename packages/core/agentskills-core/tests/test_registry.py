"""Tests for SkillRegistry."""

from unittest.mock import AsyncMock

import pytest

from agentskills_core import Skill, SkillNotFoundError, SkillProvider, SkillRegistry


def _mock_provider(
    skill_id: str = "incident-response",
    description: str = "Test.",
    body: str = "# Instructions",
) -> AsyncMock:
    provider = AsyncMock(spec=SkillProvider)
    provider.get_metadata.return_value = {
        "name": skill_id,
        "description": description,
    }
    provider.get_body.return_value = body
    return provider


class TestSkillRegistry:
    async def test_register_and_list(self):
        registry = SkillRegistry()
        await registry.register("incident-response", _mock_provider())
        skills = registry.list_skills()
        assert len(skills) == 1
        assert isinstance(skills[0], Skill)
        assert skills[0].get_id() == "incident-response"

    async def test_list_skills_sorted(self):
        registry = SkillRegistry()
        await registry.register("bravo", _mock_provider("bravo"))
        await registry.register("alpha", _mock_provider("alpha"))
        ids = [s.get_id() for s in registry.list_skills()]
        assert ids == ["alpha", "bravo"]

    async def test_get_returns_skill(self):
        registry = SkillRegistry()
        await registry.register("incident-response", _mock_provider())
        skill = registry.get_skill("incident-response")
        assert isinstance(skill, Skill)
        assert skill.get_id() == "incident-response"

    async def test_get_returns_same_instance(self):
        registry = SkillRegistry()
        await registry.register("incident-response", _mock_provider())
        skill_a = registry.get_skill("incident-response")
        skill_b = registry.get_skill("incident-response")
        assert skill_a is skill_b

    async def test_get_missing_skill_raises(self):
        registry = SkillRegistry()
        await registry.register("incident-response", _mock_provider())
        with pytest.raises(SkillNotFoundError, match="nonexistent"):
            registry.get_skill("nonexistent")

    def test_empty_registry(self):
        registry = SkillRegistry()
        assert registry.list_skills() == []

    async def test_list_skills_returns_same_instances(self):
        registry = SkillRegistry()
        await registry.register("incident-response", _mock_provider())
        skill_from_list = registry.list_skills()[0]
        skill_from_get = registry.get_skill("incident-response")
        assert skill_from_list is skill_from_get

    async def test_duplicate_skill_id_raises(self):
        registry = SkillRegistry()
        await registry.register("incident-response", _mock_provider())
        with pytest.raises(ValueError, match="Duplicate skill_id"):
            await registry.register("incident-response", _mock_provider())

    async def test_get_delegates_to_correct_provider(self):
        p1 = _mock_provider("incident-response")
        p2 = _mock_provider("api-style-guide")
        registry = SkillRegistry()
        await registry.register("incident-response", p1)
        await registry.register("api-style-guide", p2)

        # Reset call counts from registration validation
        p1.get_metadata.reset_mock()
        p2.get_metadata.reset_mock()

        skill_ir = registry.get_skill("incident-response")
        _ = await skill_ir.get_metadata()
        p1.get_metadata.assert_called_with("incident-response")
        p2.get_metadata.assert_not_called()

    async def test_register_validates_provider(self):
        """Registration fails if the provider cannot serve the skill."""
        provider = AsyncMock(spec=SkillProvider)
        provider.get_metadata.side_effect = SkillNotFoundError("SKILL.md not found")
        provider.get_body.side_effect = SkillNotFoundError("SKILL.md not found")
        registry = SkillRegistry()
        with pytest.raises(ValueError, match="failed validation"):
            await registry.register("bad-skill", provider)
        # Skill should NOT be registered after a failed validation
        assert len(registry.list_skills()) == 0

    async def test_register_rejects_invalid_metadata(self):
        """Registration fails if metadata does not satisfy spec."""
        provider = _mock_provider(
            skill_id="incident-response",
            description="",  # missing description
        )
        registry = SkillRegistry()
        with pytest.raises(ValueError, match="missing required 'description'"):
            await registry.register("incident-response", provider)
        assert len(registry.list_skills()) == 0


class TestBatchRegistration:
    async def test_register_batch(self):
        registry = SkillRegistry()
        await registry.register(
            [
                ("alpha", _mock_provider("alpha")),
                ("bravo", _mock_provider("bravo")),
            ]
        )
        assert len(registry.list_skills()) == 2
        ids = [s.get_id() for s in registry.list_skills()]
        assert ids == ["alpha", "bravo"]

    async def test_batch_is_atomic_on_validation_failure(self):
        """If one skill in the batch fails, none are registered."""
        good = _mock_provider("good-skill")
        bad = _mock_provider("bad-skill", description="")
        registry = SkillRegistry()
        with pytest.raises(ValueError, match="failed validation"):
            await registry.register(
                [
                    ("good-skill", good),
                    ("bad-skill", bad),
                ]
            )
        assert len(registry.list_skills()) == 0

    async def test_batch_rejects_duplicate_within_batch(self):
        registry = SkillRegistry()
        with pytest.raises(ValueError, match="Duplicate skill_id"):
            await registry.register(
                [
                    ("same", _mock_provider("same")),
                    ("same", _mock_provider("same")),
                ]
            )
        assert len(registry.list_skills()) == 0

    async def test_batch_rejects_duplicate_with_existing(self):
        registry = SkillRegistry()
        await registry.register("alpha", _mock_provider("alpha"))
        with pytest.raises(ValueError, match="Duplicate skill_id"):
            await registry.register(
                [
                    ("alpha", _mock_provider("alpha")),
                    ("bravo", _mock_provider("bravo")),
                ]
            )
        # Only the original should remain
        assert len(registry.list_skills()) == 1

    async def test_batch_empty_list(self):
        registry = SkillRegistry()
        await registry.register([])
        assert len(registry.list_skills()) == 0

    async def test_single_register_requires_provider(self):
        registry = SkillRegistry()
        with pytest.raises(ValueError, match="provider is required"):
            await registry.register("incident-response")


class TestRegistryEdgeCases:
    """Tests for registry edge cases and uncovered branches."""

    async def test_register_invalid_type_raises(self):
        """register() with non-string, non-list first arg raises ValueError."""
        registry = SkillRegistry()
        with pytest.raises(ValueError, match="Expected a skill_id string or a list"):
            await registry.register(123)  # type: ignore[arg-type]

    async def test_batch_with_provider_raises(self):
        """register() batch call with provider arg raises ValueError."""
        registry = SkillRegistry()
        with pytest.raises(ValueError, match="provider must not be passed"):
            await registry.register(
                [("alpha", _mock_provider("alpha"))],
                _mock_provider("alpha"),
            )

    async def test_repr_empty(self):
        registry = SkillRegistry()
        assert repr(registry) == "SkillRegistry(0 skills)"

    async def test_repr_singular(self):
        registry = SkillRegistry()
        await registry.register("alpha", _mock_provider("alpha"))
        assert repr(registry) == "SkillRegistry(1 skill)"

    async def test_repr_plural(self):
        registry = SkillRegistry()
        await registry.register("alpha", _mock_provider("alpha"))
        await registry.register("bravo", _mock_provider("bravo"))
        assert repr(registry) == "SkillRegistry(2 skills)"
