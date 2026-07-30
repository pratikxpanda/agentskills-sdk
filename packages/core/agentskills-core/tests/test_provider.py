"""Tests for SkillProvider ABC."""

import pytest

from agentskills_core import (
    RESOURCE_KINDS,
    ResourceListingNotSupportedError,
    SkillProvider,
)


class _StubProvider(SkillProvider):
    async def get_metadata(self, skill_id: str) -> dict:
        return {"name": skill_id, "description": "A test skill."}

    async def get_body(self, skill_id: str) -> str:
        return "# Test"

    async def get_script(self, skill_id: str, name: str) -> bytes:
        return b""

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        return b""

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        return b""


class TestResourceListingCapability:
    """Listing is optional: opt in by overriding, declare via the flag."""

    def test_default_flag_is_false(self):
        assert _StubProvider().supports_resource_listing is False

    async def test_default_raises_rather_than_returning_empty(self):
        """'Cannot enumerate' must not be reported as 'has no resources'."""
        with pytest.raises(ResourceListingNotSupportedError, match="_StubProvider"):
            await _StubProvider().list_resources("some-skill")

    async def test_is_a_not_implemented_error(self):
        """Callers that only know the stdlib hierarchy can still catch it."""
        with pytest.raises(NotImplementedError):
            await _StubProvider().list_resources("some-skill")

    async def test_subclass_can_opt_in(self):
        class ListingProvider(_StubProvider):
            supports_resource_listing = True

            async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
                return {kind: [] for kind in RESOURCE_KINDS}

        provider = ListingProvider()
        assert provider.supports_resource_listing is True
        assert await provider.list_resources("s") == {
            "references": [],
            "scripts": [],
            "assets": [],
        }

    def test_resource_kinds_are_the_spec_categories(self):
        assert RESOURCE_KINDS == ("references", "scripts", "assets")


class TestSkillProviderABC:
    """SkillProvider cannot be instantiated directly."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            SkillProvider()  # type: ignore[abstract]

    def test_concrete_subclass_works(self):
        """A fully-implemented subclass can be instantiated."""
        provider = _StubProvider()
        # Verify the instance was created — async methods are tested elsewhere
        assert provider is not None

    def test_partial_implementation_raises(self):
        """A subclass missing abstract methods cannot be instantiated."""

        class PartialProvider(SkillProvider):
            async def get_metadata(self, skill_id: str) -> dict:
                return {}

        with pytest.raises(TypeError):
            PartialProvider()  # type: ignore[abstract]
