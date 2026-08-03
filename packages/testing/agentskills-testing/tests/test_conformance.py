"""The conformance suite, run against the in-memory provider — and against
providers broken on purpose, to prove the suite would notice.

A test kit nobody has watched fail is a kit with unknown coverage.  Each
case here breaks exactly one clause of the contract and asserts that the
matching suite method rejects it.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentskills_core import (
    DiscoveryNotSupportedError,
    ResourceListingNotSupportedError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillProvider,
)
from agentskills_testing import (
    ASSET_BYTES,
    ASSET_NAME,
    MISSING_ID,
    REFERENCE_BYTES,
    REFERENCE_NAME,
    SCRIPT_BYTES,
    SCRIPT_NAME,
    SKILL_ID,
    InMemorySkillProvider,
    ProviderConformanceSuite,
    build_skill,
)

#: What a suite method raises when it rejects a provider — an assertion
#: that failed, or a ``pytest.raises`` block whose exception never came.
FAILURE = (AssertionError, pytest.fail.Exception)


def conforming_provider(**kwargs: Any) -> InMemorySkillProvider:
    """Build a provider populated exactly per the documented contract."""
    return InMemorySkillProvider(
        {
            SKILL_ID: build_skill(
                SKILL_ID,
                references={REFERENCE_NAME: REFERENCE_BYTES},
                scripts={SCRIPT_NAME: SCRIPT_BYTES},
                assets={ASSET_NAME: ASSET_BYTES},
            )
        },
        **kwargs,
    )


class TestInMemoryProviderConformance(ProviderConformanceSuite):
    """The in-memory provider must pass the suite it ships with."""

    @pytest.fixture
    def provider(self) -> SkillProvider:
        return conforming_provider()


class TestInMemoryProviderWithoutListing(ProviderConformanceSuite):
    """And it must still pass with resource listing switched off."""

    @pytest.fixture
    def provider(self) -> SkillProvider:
        return conforming_provider(supports_resource_listing=False)


class TestInMemoryProviderWithoutDiscovery(ProviderConformanceSuite):
    """And with discovery switched off, which is the HTTP default."""

    @pytest.fixture
    def provider(self) -> SkillProvider:
        return conforming_provider(supports_discovery=False)


# ----------------------------------------------------------------------
# Providers broken on purpose
# ----------------------------------------------------------------------


class _ReturnsNoneForUnknownSkills(InMemorySkillProvider):
    """The classic: a missing skill is reported as an empty one."""

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        try:
            return await super().get_metadata(skill_id)
        except SkillNotFoundError:
            return {}


class _ResolvesTraversal(InMemorySkillProvider):
    """Refuses nothing — every identifier reaches the backend."""

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        return {"name": SKILL_ID, "description": "whatever you asked for"}

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        return b"the contents of ../../etc/passwd"


class _LeaksTheBody(InMemorySkillProvider):
    """Defeats progressive disclosure by inlining the body in metadata."""

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        metadata = await super().get_metadata(skill_id)
        metadata["body"] = await self.get_body(skill_id)
        return metadata


class _SharesMutableMetadata(SkillProvider):
    """Hands every caller the same dict."""

    supports_resource_listing = False

    def __init__(self) -> None:
        self._metadata = {"name": SKILL_ID, "description": "shared"}

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        return self._metadata

    async def get_body(self, skill_id: str) -> str:
        return "body"

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(name)

    async def get_script(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(name)

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(name)


class _LiesAboutListing(InMemorySkillProvider):
    """Advertises listing, then refuses to list."""

    supports_resource_listing = True

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        raise ResourceListingNotSupportedError("changed my mind")


class _ReturnsStrResources(InMemorySkillProvider):
    """Decodes resources on the way out, so a PNG is unreachable."""

    async def get_script(self, skill_id: str, name: str) -> Any:
        return (await super().get_script(skill_id, name)).decode()


class _ReadsOnce(InMemorySkillProvider):
    """Streams without buffering: the second read comes back empty."""

    def __init__(self) -> None:
        super().__init__({SKILL_ID: build_skill(SKILL_ID)})
        self._spent = False

    async def get_body(self, skill_id: str) -> str:
        if self._spent:
            return ""
        self._spent = True
        return await super().get_body(skill_id)


class _LiesAboutDiscovery(InMemorySkillProvider):
    """Advertises discovery, then refuses to enumerate."""

    supports_discovery = True

    async def discover(self) -> list[str]:
        raise DiscoveryNotSupportedError("changed my mind")


class _DiscoversPhantoms(InMemorySkillProvider):
    """Reports a skill it cannot serve, which poisons ``register_all``."""

    async def discover(self) -> list[str]:
        return [*self.skill_ids(), MISSING_ID]


class TestTheSuiteCatchesBrokenProviders:
    """Every clause of the contract, violated and caught."""

    @staticmethod
    def _suite() -> ProviderConformanceSuite:
        return ProviderConformanceSuite()

    async def test_swallowed_missing_skill_is_caught(self):
        with pytest.raises(FAILURE):
            await self._suite().test_unknown_skill_raises_skill_not_found(
                _ReturnsNoneForUnknownSkills()
            )

    @pytest.mark.parametrize("identifier", ["../etc/passwd", ".."])
    async def test_resolved_traversal_skill_id_is_caught(self, identifier: str):
        with pytest.raises(FAILURE):
            await self._suite().test_traversal_skill_id_is_refused(_ResolvesTraversal(), identifier)

    async def test_resolved_traversal_resource_name_is_caught(self):
        with pytest.raises(FAILURE):
            await self._suite().test_traversal_resource_name_is_refused(
                _ResolvesTraversal(), "references", "../etc/passwd"
            )

    async def test_body_leaked_into_metadata_is_caught(self):
        provider = _LeaksTheBody({SKILL_ID: build_skill(SKILL_ID)})

        with pytest.raises(FAILURE):
            await self._suite().test_metadata_excludes_the_body(provider)

    async def test_shared_mutable_metadata_is_caught(self):
        with pytest.raises(FAILURE):
            await self._suite().test_metadata_is_not_shared_mutable_state(_SharesMutableMetadata())

    async def test_a_listing_capability_that_lies_is_caught(self):
        with pytest.raises(FAILURE):
            await self._suite().test_listing_matches_the_declared_capability(_LiesAboutListing())

    async def test_a_decoded_resource_is_caught(self):
        provider = _ReturnsStrResources(
            {SKILL_ID: build_skill(SKILL_ID, scripts={SCRIPT_NAME: SCRIPT_BYTES})}
        )

        with pytest.raises(FAILURE):
            await self._suite().test_resource_returns_exact_bytes(provider, "scripts")

    async def test_a_provider_that_reads_once_is_caught(self):
        with pytest.raises(FAILURE):
            await self._suite().test_repeated_reads_agree(_ReadsOnce())

    async def test_a_missing_resource_that_returns_empty_is_caught(self):
        class _EmptyForMissing(InMemorySkillProvider):
            async def get_asset(self, skill_id: str, name: str) -> bytes:
                return b""

        with pytest.raises(FAILURE):
            await self._suite().test_unknown_resource_raises_resource_not_found(
                _EmptyForMissing({SKILL_ID: build_skill(SKILL_ID)}), "assets"
            )

    async def test_metadata_without_a_description_is_caught(self):
        provider = InMemorySkillProvider(
            {SKILL_ID: build_skill(SKILL_ID, metadata={"description": "   "})}
        )

        with pytest.raises(FAILURE):
            await self._suite().test_metadata_has_the_required_fields(provider)

    async def test_a_resource_of_an_unknown_skill_that_succeeds_is_caught(self):
        with pytest.raises(FAILURE):
            await self._suite().test_resource_of_unknown_skill_is_refused(
                _ResolvesTraversal(), "references"
            )

    async def test_a_listing_that_ignores_the_skill_id_is_caught(self):
        class _ListsAnything(InMemorySkillProvider):
            async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
                return {"references": [], "scripts": [], "assets": []}

        with pytest.raises(FAILURE):
            await self._suite().test_listing_of_unknown_skill_is_refused(
                _ListsAnything({SKILL_ID: build_skill(SKILL_ID)})
            )

    async def test_a_discovery_capability_that_lies_is_caught(self):
        with pytest.raises(FAILURE):
            await self._suite().test_discovery_matches_the_declared_capability(
                _LiesAboutDiscovery()
            )

    async def test_discovery_that_reports_an_unreadable_skill_is_caught(self):
        provider = _DiscoversPhantoms({SKILL_ID: build_skill(SKILL_ID)})

        with pytest.raises(SkillNotFoundError):
            await self._suite().test_discovered_skills_are_readable(provider)

    async def test_a_silent_discovery_refusal_is_caught(self):
        """Returning nothing instead of raising is the failure ADR 0002 exists to stop."""

        class _EmptyInsteadOfRaising(InMemorySkillProvider):
            supports_discovery = False

            async def discover(self) -> list[str]:
                return []

        with pytest.raises(FAILURE):
            await self._suite().test_discovery_matches_the_declared_capability(
                _EmptyInsteadOfRaising({SKILL_ID: build_skill(SKILL_ID)})
            )


class TestTheContractItself:
    def test_the_contract_names_the_fixture_skill(self):
        from agentskills_testing import CONTRACT

        assert SKILL_ID in CONTRACT
        assert MISSING_ID in CONTRACT
