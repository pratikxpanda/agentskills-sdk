"""Tests for SkillRegistry."""

from unittest.mock import AsyncMock

import pytest

from agentskills_core import (
    DiscoveryNotSupportedError,
    Skill,
    SkillNotFoundError,
    SkillProvider,
    SkillRegistry,
)


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


class _DiscoverableProvider(SkillProvider):
    """A minimal real provider mapping skill ID to description.

    Hand-written rather than taken from ``agentskills-testing``, which
    depends on this package.  An empty description makes a skill fail
    validation, which is how the failure paths below are built.
    """

    supports_discovery = True

    def __init__(self, skills: dict[str, str]) -> None:
        self._skills = skills

    async def discover(self) -> list[str]:
        return sorted(self._skills)

    async def get_metadata(self, skill_id: str) -> dict:
        if skill_id not in self._skills:
            raise SkillNotFoundError(skill_id)
        return {"name": skill_id, "description": self._skills[skill_id]}

    async def get_body(self, skill_id: str) -> str:
        return "# Instructions"

    async def get_script(self, skill_id: str, name: str) -> bytes:
        return b""

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        return b""

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        return b""


class _NoDiscoveryProvider(_DiscoverableProvider):
    """The same provider with the capability turned off."""

    supports_discovery = False
    discover = SkillProvider.discover


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


class TestSectionAccess:
    """The registry's section shortcuts, which the integrations wrap."""

    @pytest.fixture()
    async def registry(self) -> SkillRegistry:
        reg = SkillRegistry()
        body = "# Title\n\nintro\n\n## Triage\n\npage the on-call"
        await reg.register("incident-response", _mock_provider(body=body))
        return reg

    async def test_get_skill_outline(self, registry):
        outline = await registry.get_skill_outline("incident-response")

        assert outline.skill_id == "incident-response"
        assert [ref.key for ref in outline.sections] == ["title", "triage"]

    async def test_get_skill_section(self, registry):
        assert "page the on-call" in await registry.get_skill_section("incident-response", "triage")

    async def test_unknown_skill_raises(self, registry):
        with pytest.raises(SkillNotFoundError):
            await registry.get_skill_outline("nonexistent")


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

    async def test_batch_reports_every_validation_failure(self):
        """Fixing a batch one error per run is a game of whack-a-mole."""
        registry = SkillRegistry()
        with pytest.raises(ValueError) as exc_info:
            await registry.register(
                [
                    ("alpha", _mock_provider("alpha", description="")),
                    ("bravo", _mock_provider("bravo", description="")),
                ]
            )
        assert "alpha" in str(exc_info.value)
        assert "bravo" in str(exc_info.value)


class TestRegisterAll:
    async def test_registers_everything_discovered(self):
        registry = SkillRegistry()
        provider = _DiscoverableProvider({"alpha": "A.", "bravo": "B."})

        assert await registry.register_all(provider) == ["alpha", "bravo"]
        assert [s.get_id() for s in registry.list_skills()] == ["alpha", "bravo"]

    async def test_an_empty_backend_registers_nothing(self):
        """Enumerated and found nothing is a success, not a failure."""
        registry = SkillRegistry()
        assert await registry.register_all(_DiscoverableProvider({})) == []
        assert registry.list_skills() == []

    async def test_unsupported_provider_raises(self):
        """A provider that cannot enumerate must not look like an empty one."""
        registry = SkillRegistry()
        with pytest.raises(DiscoveryNotSupportedError):
            await registry.register_all(_NoDiscoveryProvider({"alpha": "A."}))
        assert registry.list_skills() == []

    async def test_reports_every_validation_failure_at_once(self):
        registry = SkillRegistry()
        provider = _DiscoverableProvider({"alpha": "", "bravo": "B.", "charlie": ""})

        with pytest.raises(ValueError) as exc_info:
            await registry.register_all(provider)

        message = str(exc_info.value)
        assert "alpha" in message
        assert "charlie" in message

    async def test_is_atomic(self):
        registry = SkillRegistry()
        provider = _DiscoverableProvider({"alpha": "A.", "bravo": ""})

        with pytest.raises(ValueError, match="failed validation"):
            await registry.register_all(provider)

        assert registry.list_skills() == []

    async def test_rejects_ids_already_registered(self):
        registry = SkillRegistry()
        await registry.register("alpha", _mock_provider("alpha"))
        provider = _DiscoverableProvider({"alpha": "A.", "bravo": "B."})

        with pytest.raises(ValueError, match="already"):
            await registry.register_all(provider)

        assert [s.get_id() for s in registry.list_skills()] == ["alpha"]

    async def test_two_providers_can_be_combined(self):
        registry = SkillRegistry()
        await registry.register_all(_DiscoverableProvider({"alpha": "A."}))
        await registry.register_all(_DiscoverableProvider({"bravo": "B."}))
        assert [s.get_id() for s in registry.list_skills()] == ["alpha", "bravo"]


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
