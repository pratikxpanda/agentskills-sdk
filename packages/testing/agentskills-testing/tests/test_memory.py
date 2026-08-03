"""Tests for the in-memory provider and content helpers."""

from __future__ import annotations

import pytest

from agentskills_core import (
    DiscoveryNotSupportedError,
    ResourceListingNotSupportedError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillProvider,
    SkillRegistry,
    validate_skill,
)
from agentskills_testing import (
    DEFAULT_BODY,
    DEFAULT_SKILL_ID,
    InMemorySkillProvider,
    build_skill,
    render_skill_md,
)


class TestBuildSkill:
    def test_defaults_produce_a_valid_skill(self):
        skill = build_skill()

        assert skill.metadata["name"] == DEFAULT_SKILL_ID
        assert skill.body == DEFAULT_BODY
        assert skill.references == {}

    async def test_defaults_pass_core_validation(self):
        registry = SkillRegistry()
        await registry.register(
            DEFAULT_SKILL_ID, InMemorySkillProvider({DEFAULT_SKILL_ID: build_skill()})
        )

        assert await validate_skill(registry.get_skill(DEFAULT_SKILL_ID)) == []

    def test_version_is_omitted_unless_asked_for(self):
        assert "version" not in build_skill().metadata
        assert build_skill(version="1.2.3").metadata["version"] == "1.2.3"

    def test_extra_metadata_wins_over_the_generated_fields(self):
        skill = build_skill("a", description="generated", metadata={"description": "explicit"})

        assert skill.metadata["description"] == "explicit"

    def test_resource_mappings_are_copied(self):
        references = {"a.md": b"a"}

        skill = build_skill(references=references)
        references["b.md"] = b"b"

        assert skill.references == {"a.md": b"a"}

    def test_resources_are_addressed_by_kind(self):
        skill = build_skill(scripts={"run.sh": b"#!/bin/sh\n"})

        assert skill.resources("scripts") == {"run.sh": b"#!/bin/sh\n"}
        assert skill.resources("assets") == {}


class TestRenderSkillMd:
    def test_round_trips_through_the_core_parser(self):
        from agentskills_core import split_frontmatter

        skill = build_skill("demo", version="1.0.0", body="# Demo\n\nDo the thing.\n")

        metadata, body = split_frontmatter(render_skill_md(skill))

        assert metadata == skill.metadata
        assert body.strip() == skill.body.strip()


class TestInMemorySkillProvider:
    def test_is_a_skill_provider(self):
        assert isinstance(InMemorySkillProvider(), SkillProvider)

    async def test_a_string_value_is_taken_as_the_body(self):
        provider = InMemorySkillProvider({"quick": "Just the body."})

        assert await provider.get_body("quick") == "Just the body."
        assert (await provider.get_metadata("quick"))["name"] == "quick"

    async def test_add_without_a_skill_builds_a_default_one(self):
        provider = InMemorySkillProvider()

        provider.add("solo")

        assert provider.skill_ids() == ["solo"]
        assert await provider.get_body("solo") == DEFAULT_BODY

    def test_add_replaces_an_existing_skill(self):
        provider = InMemorySkillProvider({"a": "first"})

        provider.add("a", "second")

        assert provider.skill_ids() == ["a"]

    def test_skill_ids_are_sorted(self):
        assert InMemorySkillProvider({"c": "", "a": "", "b": ""}).skill_ids() == ["a", "b", "c"]

    async def test_metadata_is_a_copy(self):
        provider = InMemorySkillProvider({"a": "body"})

        (await provider.get_metadata("a"))["name"] = "mutated"

        assert (await provider.get_metadata("a"))["name"] == "a"

    @pytest.mark.parametrize("kind", ["references", "scripts", "assets"])
    async def test_each_resource_kind_round_trips(self, kind: str):
        provider = InMemorySkillProvider({"a": build_skill("a", **{kind: {"f.txt": b"data"}})})
        getter = {
            "references": provider.get_reference,
            "scripts": provider.get_script,
            "assets": provider.get_asset,
        }[kind]

        assert await getter("a", "f.txt") == b"data"

    async def test_unknown_skill_raises_skill_not_found(self):
        with pytest.raises(SkillNotFoundError, match="Skill not found"):
            await InMemorySkillProvider().get_body("nope")

    async def test_unknown_resource_raises_resource_not_found(self):
        provider = InMemorySkillProvider({"a": "body"})

        with pytest.raises(ResourceNotFoundError, match="not found in scripts/"):
            await provider.get_script("a", "nope.sh")

    async def test_listing_returns_every_kind(self):
        provider = InMemorySkillProvider(
            {"a": build_skill("a", scripts={"b.sh": b"", "a.sh": b""})}
        )

        assert await provider.list_resources("a") == {
            "references": [],
            "scripts": ["a.sh", "b.sh"],
            "assets": [],
        }

    async def test_listing_can_be_disabled(self):
        provider = InMemorySkillProvider({"a": "body"}, supports_resource_listing=False)

        assert provider.supports_resource_listing is False
        with pytest.raises(ResourceListingNotSupportedError):
            await provider.list_resources("a")

    async def test_listing_an_unknown_skill_raises_skill_not_found(self):
        with pytest.raises(SkillNotFoundError):
            await InMemorySkillProvider().list_resources("nope")

    async def test_discovery_returns_sorted_ids(self):
        provider = InMemorySkillProvider({"c": "", "a": "", "b": ""})

        assert await provider.discover() == ["a", "b", "c"]

    async def test_discovery_can_be_disabled(self):
        provider = InMemorySkillProvider({"a": "body"}, supports_discovery=False)

        assert provider.supports_discovery is False
        with pytest.raises(DiscoveryNotSupportedError):
            await provider.discover()

    async def test_registers_wholesale(self):
        provider = InMemorySkillProvider({"alpha": "# Alpha", "bravo": "# Bravo"})
        registry = SkillRegistry()

        assert await registry.register_all(provider) == ["alpha", "bravo"]

    @pytest.mark.parametrize("bad", ["../etc", "a/b", "a\\b", "x\x00y", ""])
    async def test_unsafe_skill_ids_are_refused(self, bad: str):
        with pytest.raises(SkillNotFoundError, match="Invalid skill_id"):
            await InMemorySkillProvider().get_metadata(bad)

    @pytest.mark.parametrize("bad", ["../etc", "a/b", "a\\b", "x\x00y", ""])
    async def test_unsafe_resource_names_are_refused(self, bad: str):
        provider = InMemorySkillProvider({"a": "body"})

        with pytest.raises(ResourceNotFoundError, match="Invalid resource name"):
            await provider.get_reference("a", bad)
