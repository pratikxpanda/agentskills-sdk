"""In-memory skill provider and content helpers.

A test that needs a skill should not need a directory or an HTTP server,
and it should not need an ``AsyncMock`` either: a mock agrees with
whatever the test asserts, including the assertions that are wrong.
:class:`InMemorySkillProvider` is a real provider that passes the same
conformance suite the filesystem and HTTP providers do.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml

from agentskills_core import (
    RESOURCE_KINDS,
    DiscoveryNotSupportedError,
    ResourceListingNotSupportedError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillProvider,
    get_logger,
)

_logger = get_logger(__name__)

DEFAULT_SKILL_ID = "incident-response"
DEFAULT_DESCRIPTION = "Diagnose and mitigate a production incident."
DEFAULT_BODY = "# Incident Response\n\nPage the on-call engineer, then open a channel.\n"

# A provider is addressed by skill ID and resource name, and both reach a
# backend that may treat them as a path segment. Anything that could
# escape one is refused before it gets that far.
_UNSAFE = ("..", "/", "\\", "\x00")


@dataclass(frozen=True)
class InMemorySkill:
    """One skill's content, held in memory.

    Attributes:
        metadata: Parsed frontmatter. Must carry ``name`` and
            ``description`` to satisfy the specification.
        body: Markdown instructions.
        references: Reference documents by filename.
        scripts: Scripts by filename.
        assets: Assets by filename.
    """

    metadata: dict[str, Any]
    body: str = DEFAULT_BODY
    references: dict[str, bytes] = field(default_factory=dict)
    scripts: dict[str, bytes] = field(default_factory=dict)
    assets: dict[str, bytes] = field(default_factory=dict)

    def resources(self, kind: str) -> dict[str, bytes]:
        """Return the resource mapping for *kind*."""
        return {"references": self.references, "scripts": self.scripts, "assets": self.assets}[kind]


def build_skill(
    skill_id: str = DEFAULT_SKILL_ID,
    *,
    description: str = DEFAULT_DESCRIPTION,
    body: str = DEFAULT_BODY,
    version: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    references: Mapping[str, bytes] | None = None,
    scripts: Mapping[str, bytes] | None = None,
    assets: Mapping[str, bytes] | None = None,
) -> InMemorySkill:
    """Build a valid :class:`InMemorySkill`.

    The defaults produce a skill that passes ``validate_skill()``, so a
    test that does not care about content does not have to invent any.

    Args:
        skill_id: Becomes the ``name`` in the frontmatter.
        description: Frontmatter description.
        body: Markdown instructions.
        version: Optional semver string.
        metadata: Extra frontmatter, merged over the generated fields.
        references: Reference documents by filename.
        scripts: Scripts by filename.
        assets: Assets by filename.

    Returns:
        A skill ready to hand to :class:`InMemorySkillProvider`.
    """
    frontmatter: dict[str, Any] = {"name": skill_id, "description": description}
    if version is not None:
        frontmatter["version"] = version
    if metadata:
        frontmatter.update(metadata)

    return InMemorySkill(
        metadata=frontmatter,
        body=body,
        references=dict(references or {}),
        scripts=dict(scripts or {}),
        assets=dict(assets or {}),
    )


def render_skill_md(skill: InMemorySkill) -> str:
    """Render *skill* as the ``SKILL.md`` text a file-backed provider would hold.

    Useful for populating a temporary directory when a test needs the
    filesystem provider rather than this one.
    """
    frontmatter = yaml.safe_dump(skill.metadata, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n\n{skill.body}"


class InMemorySkillProvider(SkillProvider):
    """A spec-compliant :class:`~agentskills_core.SkillProvider` backed by a dict.

    Args:
        skills: Skills by ID. A plain string value is taken as the body
            of a default skill, so the common case stays short.
        supports_resource_listing: Set ``False`` to emulate a backend
            that cannot enumerate, which is what the HTTP provider does
            without a manifest.
        supports_discovery: Set ``False`` to emulate a backend that
            cannot list the skills it holds.

    Example::

        provider = InMemorySkillProvider({"incident-response": build_skill()})
        registry = SkillRegistry()
        await registry.register("incident-response", provider)
    """

    def __init__(
        self,
        skills: Mapping[str, InMemorySkill | str] | None = None,
        *,
        supports_resource_listing: bool = True,
        supports_discovery: bool = True,
    ) -> None:
        self._skills: dict[str, InMemorySkill] = {}
        self.supports_resource_listing = supports_resource_listing
        self.supports_discovery = supports_discovery
        for skill_id, skill in (skills or {}).items():
            self.add(skill_id, skill)

    def add(self, skill_id: str, skill: InMemorySkill | str | None = None) -> InMemorySkill:
        """Add or replace a skill.

        Args:
            skill_id: ID to register the skill under.
            skill: The skill, or a string taken as its body. Omit it for
                a default skill named after *skill_id*.

        Returns:
            The stored skill.
        """
        if skill is None:
            skill = build_skill(skill_id)
        elif isinstance(skill, str):
            skill = build_skill(skill_id, body=skill)
        self._skills[skill_id] = skill
        _logger.debug("Added in-memory skill %r", skill_id)
        return skill

    def skill_ids(self) -> list[str]:
        """Return the registered skill IDs, sorted."""
        return sorted(self._skills)

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        """Return a copy of the skill's frontmatter."""
        return dict(self._get(skill_id).metadata)

    async def get_body(self, skill_id: str) -> str:
        """Return the skill's markdown body."""
        return self._get(skill_id).body

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        """Return a reference document."""
        return self._resource(skill_id, "references", name)

    async def get_script(self, skill_id: str, name: str) -> bytes:
        """Return a script."""
        return self._resource(skill_id, "scripts", name)

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        """Return an asset."""
        return self._resource(skill_id, "assets", name)

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        """Return the skill's resource names, grouped by kind and sorted.

        Raises:
            ResourceListingNotSupportedError: If the provider was built
                with ``supports_resource_listing=False``.
            SkillNotFoundError: If the skill is unknown.
        """
        if not self.supports_resource_listing:
            raise ResourceListingNotSupportedError(
                "InMemorySkillProvider was built with resource listing disabled."
            )
        skill = self._get(skill_id)
        return {kind: sorted(skill.resources(kind)) for kind in RESOURCE_KINDS}

    async def discover(self) -> list[str]:
        """Return the stored skill IDs, sorted.

        Raises:
            DiscoveryNotSupportedError: If the provider was built with
                ``supports_discovery=False``.
        """
        if not self.supports_discovery:
            raise DiscoveryNotSupportedError(
                "InMemorySkillProvider was built with discovery disabled."
            )
        return self.skill_ids()

    def _get(self, skill_id: str) -> InMemorySkill:
        _reject_unsafe(skill_id, SkillNotFoundError, "skill_id")
        try:
            return self._skills[skill_id]
        except KeyError:
            raise SkillNotFoundError(f"Skill not found: {skill_id!r}") from None

    def _resource(self, skill_id: str, kind: str, name: str) -> bytes:
        skill = self._get(skill_id)
        _reject_unsafe(name, ResourceNotFoundError, "resource name")
        try:
            return skill.resources(kind)[name]
        except KeyError:
            raise ResourceNotFoundError(
                f"Resource {name!r} not found in {kind}/ for skill {skill_id!r}"
            ) from None


def _reject_unsafe(value: str, error: type[Exception], label: str) -> None:
    """Refuse an identifier that could escape its container."""
    if not value or any(part in value for part in _UNSAFE):
        raise error(f"Invalid {label}: {value!r}")
