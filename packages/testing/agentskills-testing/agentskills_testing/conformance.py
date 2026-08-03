"""The provider conformance suite.

``SkillProvider`` is an ABC, which enforces that five methods exist and
nothing about what they do.  The requirements that actually matter are
the ones an ABC cannot express: that an unknown ID raises the documented
exception rather than returning ``None``, that a traversal-shaped
identifier is refused rather than resolved, and that a provider
advertising resource listing or discovery can actually deliver it.

Subclass :class:`ProviderConformanceSuite`, supply a ``provider``
fixture populated per :data:`CONTRACT`, and pytest collects the whole
suite against your implementation.

Every test is marked ``asyncio`` explicitly so the suite runs under
``pytest-asyncio`` in either strict or auto mode — a kit that only works
under one project's configuration is not a kit.
"""

from __future__ import annotations

import asyncio

import pytest

from agentskills_core import (
    RESOURCE_KINDS,
    AgentSkillsError,
    DiscoveryNotSupportedError,
    ResourceListingNotSupportedError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillProvider,
)

#: The skill a conforming ``provider`` fixture must expose.
SKILL_ID = "conformance-skill"

#: The reference document that skill must contain, and its exact bytes.
REFERENCE_NAME = "notes.md"
REFERENCE_BYTES = b"# Notes\n\nA reference document.\n"

#: The script that skill must contain, and its exact bytes.
SCRIPT_NAME = "run.sh"
SCRIPT_BYTES = b"#!/bin/sh\necho conformance\n"

#: The asset that skill must contain, and its exact bytes.
ASSET_NAME = "diagram.svg"
ASSET_BYTES = b"<svg></svg>\n"

#: An ID no conforming fixture may define.
MISSING_ID = "no-such-skill-anywhere"

#: A resource name no conforming fixture may define.
MISSING_RESOURCE = "no-such-resource.txt"

CONTRACT = f"""\
The `provider` fixture must expose exactly one skill:

  id           {SKILL_ID}
  metadata     name == {SKILL_ID!r}, plus a non-empty description
  body         non-empty markdown
  references/  {REFERENCE_NAME} containing {REFERENCE_BYTES!r}
  scripts/     {SCRIPT_NAME} containing {SCRIPT_BYTES!r}
  assets/      {ASSET_NAME} containing {ASSET_BYTES!r}

It must not define a skill called {MISSING_ID!r} or any resource called
{MISSING_RESOURCE!r}.  A provider that sets `supports_discovery` must
report exactly one skill, {SKILL_ID!r}.
"""

#: Identifiers a provider must refuse rather than resolve.  Each is a
#: real technique: parent traversal, an absolute path, a Windows path, a
#: percent-encoded traversal that a URL-building backend may decode, and
#: a NUL byte that truncates a C string.
TRAVERSAL_IDENTIFIERS = (
    "../etc/passwd",
    "..",
    "a/../../b",
    "/etc/passwd",
    "..\\..\\windows\\system32",
    "%2e%2e%2fetc%2fpasswd",
    "ok\x00.md",
)

_RESOURCE_GETTERS = {
    "references": "get_reference",
    "scripts": "get_script",
    "assets": "get_asset",
}

_EXPECTED_RESOURCES = {
    "references": (REFERENCE_NAME, REFERENCE_BYTES),
    "scripts": (SCRIPT_NAME, SCRIPT_BYTES),
    "assets": (ASSET_NAME, ASSET_BYTES),
}


class ProviderConformanceSuite:
    """Assertions every :class:`~agentskills_core.SkillProvider` must satisfy.

    Subclass it and provide a ``provider`` fixture::

        class TestMyProvider(ProviderConformanceSuite):
            @pytest.fixture
            def provider(self):
                return MyProvider(...)

    The fixture must be populated per :data:`CONTRACT`.  Nothing here is
    opt-out: a provider that cannot pass these is not a provider, it is
    a class with the right method names.
    """

    @pytest.fixture
    def provider(self) -> SkillProvider:
        """Return the provider under test, populated per :data:`CONTRACT`."""
        raise NotImplementedError(f"Override the 'provider' fixture.\n\n{CONTRACT}")

    # -- Identity -------------------------------------------------------

    def test_is_a_skill_provider(self, provider: SkillProvider) -> None:
        assert isinstance(provider, SkillProvider)

    # -- Metadata and body ---------------------------------------------

    @pytest.mark.asyncio
    async def test_metadata_has_the_required_fields(self, provider: SkillProvider) -> None:
        metadata = await provider.get_metadata(SKILL_ID)

        assert isinstance(metadata, dict)
        assert metadata.get("name") == SKILL_ID
        assert isinstance(metadata.get("description"), str)
        assert metadata["description"].strip()

    @pytest.mark.asyncio
    async def test_metadata_excludes_the_body(self, provider: SkillProvider) -> None:
        metadata = await provider.get_metadata(SKILL_ID)
        body = await provider.get_body(SKILL_ID)

        assert body.strip()
        # Progressive disclosure is the whole point: a metadata call that
        # carries the body has already spent the tokens it exists to save.
        assert all(value != body for value in metadata.values())

    @pytest.mark.asyncio
    async def test_metadata_is_not_shared_mutable_state(self, provider: SkillProvider) -> None:
        first = await provider.get_metadata(SKILL_ID)
        first["description"] = "mutated by a caller"

        second = await provider.get_metadata(SKILL_ID)

        assert second["description"] != "mutated by a caller"

    @pytest.mark.asyncio
    async def test_repeated_reads_agree(self, provider: SkillProvider) -> None:
        # A provider that streams without buffering passes once and then
        # returns empty. Caching bugs surface the same way.
        assert await provider.get_body(SKILL_ID) == await provider.get_body(SKILL_ID)
        assert await provider.get_metadata(SKILL_ID) == await provider.get_metadata(SKILL_ID)

    @pytest.mark.asyncio
    async def test_unknown_skill_raises_skill_not_found(self, provider: SkillProvider) -> None:
        with pytest.raises(SkillNotFoundError):
            await provider.get_metadata(MISSING_ID)
        with pytest.raises(SkillNotFoundError):
            await provider.get_body(MISSING_ID)

    # -- Resources ------------------------------------------------------

    @pytest.mark.parametrize("kind", RESOURCE_KINDS)
    @pytest.mark.asyncio
    async def test_resource_returns_exact_bytes(self, provider: SkillProvider, kind: str) -> None:
        name, expected = _EXPECTED_RESOURCES[kind]

        data = await getattr(provider, _RESOURCE_GETTERS[kind])(SKILL_ID, name)

        # bytes, not str: a resource may be a PNG, and decoding it on the
        # way out makes that unreachable.
        assert isinstance(data, bytes)
        assert data == expected

    @pytest.mark.parametrize("kind", RESOURCE_KINDS)
    @pytest.mark.asyncio
    async def test_unknown_resource_raises_resource_not_found(
        self, provider: SkillProvider, kind: str
    ) -> None:
        with pytest.raises(ResourceNotFoundError):
            await getattr(provider, _RESOURCE_GETTERS[kind])(SKILL_ID, MISSING_RESOURCE)

    @pytest.mark.parametrize("kind", RESOURCE_KINDS)
    @pytest.mark.asyncio
    async def test_resource_of_unknown_skill_is_refused(
        self, provider: SkillProvider, kind: str
    ) -> None:
        name, _ = _EXPECTED_RESOURCES[kind]

        with pytest.raises((SkillNotFoundError, ResourceNotFoundError)):
            await getattr(provider, _RESOURCE_GETTERS[kind])(MISSING_ID, name)

    # -- Resource listing ----------------------------------------------

    @pytest.mark.asyncio
    async def test_listing_matches_the_declared_capability(self, provider: SkillProvider) -> None:
        # The flag is what callers branch on, so a provider whose flag
        # and behaviour disagree breaks them whichever way it lies.
        if provider.supports_resource_listing:
            try:
                listing = await provider.list_resources(SKILL_ID)
            except ResourceListingNotSupportedError as exc:
                pytest.fail(
                    f"supports_resource_listing is True but list_resources() refused to list: {exc}"
                )
            assert set(listing) == set(RESOURCE_KINDS)
            for kind in RESOURCE_KINDS:
                assert listing[kind] == sorted(listing[kind])
                expected_name, _ = _EXPECTED_RESOURCES[kind]
                assert expected_name in listing[kind]
        else:
            with pytest.raises(ResourceListingNotSupportedError):
                await provider.list_resources(SKILL_ID)

    @pytest.mark.asyncio
    async def test_listing_of_unknown_skill_is_refused(self, provider: SkillProvider) -> None:
        if not provider.supports_resource_listing:
            pytest.skip("provider does not support resource listing")

        with pytest.raises(SkillNotFoundError):
            await provider.list_resources(MISSING_ID)

    # -- Skill discovery ------------------------------------------------

    @pytest.mark.asyncio
    async def test_discovery_matches_the_declared_capability(self, provider: SkillProvider) -> None:
        if provider.supports_discovery:
            try:
                skill_ids = await provider.discover()
            except DiscoveryNotSupportedError as exc:
                pytest.fail(f"supports_discovery is True but discover() refused: {exc}")
            assert isinstance(skill_ids, list)
            # The contract fixture holds exactly one skill, so this also
            # pins sortedness and the absence of duplicates.
            assert skill_ids == [SKILL_ID]
        else:
            with pytest.raises(DiscoveryNotSupportedError):
                await provider.discover()

    @pytest.mark.asyncio
    async def test_discovered_skills_are_readable(self, provider: SkillProvider) -> None:
        if not provider.supports_discovery:
            pytest.skip("provider does not support discovery")

        # register_all() validates everything discover() returns, so an ID
        # that cannot be read poisons the whole registration.
        for skill_id in await provider.discover():
            assert await provider.get_metadata(skill_id)

    # -- Security -------------------------------------------------------

    @pytest.mark.parametrize("identifier", TRAVERSAL_IDENTIFIERS)
    @pytest.mark.asyncio
    async def test_traversal_skill_id_is_refused(
        self, provider: SkillProvider, identifier: str
    ) -> None:
        with pytest.raises(SkillNotFoundError):
            await provider.get_metadata(identifier)

    @pytest.mark.parametrize("identifier", TRAVERSAL_IDENTIFIERS)
    @pytest.mark.parametrize("kind", RESOURCE_KINDS)
    @pytest.mark.asyncio
    async def test_traversal_resource_name_is_refused(
        self, provider: SkillProvider, kind: str, identifier: str
    ) -> None:
        with pytest.raises(ResourceNotFoundError):
            await getattr(provider, _RESOURCE_GETTERS[kind])(SKILL_ID, identifier)

    # -- Concurrency ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_reads_are_concurrency_safe(self, provider: SkillProvider) -> None:
        # Twenty overlapping reads through one provider instance. A
        # provider holding per-call state on self returns the wrong
        # skill's content here and nowhere else.
        bodies = await asyncio.gather(*(provider.get_body(SKILL_ID) for _ in range(20)))

        assert len(set(bodies)) == 1


class ContentLimitConformanceSuite:
    """Assertions for providers that read bytes they did not author.

    A size limit is not part of the universal contract — an in-memory
    provider has nothing to bound, and demanding one would be asserting a
    filesystem's constraints against a dict.  It *is* required of any
    provider reading from disk, a network, or anything else a caller can
    grow without asking.

    Supply a ``limited_provider`` fixture whose limit is small enough
    that the fixture's own content exceeds it::

        class TestMyProviderLimits(ContentLimitConformanceSuite):
            @pytest.fixture
            def limited_provider(self):
                return MyProvider(..., max_bytes=8)
    """

    @pytest.fixture
    def limited_provider(self) -> SkillProvider:
        """Return a provider whose size limit the contract skill exceeds."""
        raise NotImplementedError(
            "Override the 'limited_provider' fixture with a provider whose "
            "size limit is smaller than the contract skill."
        )

    @pytest.mark.asyncio
    async def test_oversized_skill_md_is_refused(self, limited_provider: SkillProvider) -> None:
        with pytest.raises(AgentSkillsError):
            await limited_provider.get_metadata(SKILL_ID)

    @pytest.mark.parametrize("kind", RESOURCE_KINDS)
    @pytest.mark.asyncio
    async def test_oversized_resource_is_refused(
        self, limited_provider: SkillProvider, kind: str
    ) -> None:
        name, _ = _EXPECTED_RESOURCES[kind]

        with pytest.raises(AgentSkillsError):
            await getattr(limited_provider, _RESOURCE_GETTERS[kind])(SKILL_ID, name)
