"""Lightweight runtime handle that delegates to a SkillProvider.

A :class:`Skill` object is the primary interface consumers use to interact
with a single Agent Skill.  It is intentionally thin: every call is
delegated to the underlying :class:`~agentskills_core.SkillProvider`,
ensuring that the handle carries no cached state and remains safe to
discard or recreate at any time.

All data-access methods are ``async`` to match the
:class:`~agentskills_core.SkillProvider` interface.

Instances are typically obtained from :meth:`SkillRegistry.get_skill
<agentskills_core.SkillRegistry.get_skill>` rather than constructed directly.
"""

from __future__ import annotations

from typing import Any

from agentskills_core.exceptions import SectionNotFoundError
from agentskills_core.provider import SkillProvider
from agentskills_core.sections import SkillOutline, outline_of, split_sections


class Skill:
    """Runtime handle to a single Agent Skill.

    All data access is delegated to the backing
    :class:`~agentskills_core.SkillProvider`.  The handle itself stores
    only the skill name and a provider reference -- no content is
    cached, and no execution logic is included.

    Args:
        skill_id: The skill name (must match the ``name`` field in the
            skill's YAML frontmatter).
        provider: The :class:`~agentskills_core.SkillProvider` that
            owns this skill.

    Example::

        skill = registry.get_skill("incident-response")
        meta = await skill.get_metadata()
        print(meta["description"])
        body = await skill.get_body()
    """

    def __init__(self, skill_id: str, provider: SkillProvider) -> None:
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise ValueError("skill_id must be a non-empty string")
        if not isinstance(provider, SkillProvider):
            raise TypeError(f"provider must be a SkillProvider, got {type(provider).__name__}")
        self._skill_id = skill_id
        self._provider = provider

    def get_id(self) -> str:
        """Return the unique skill name, matching the frontmatter ``name``."""
        return self._skill_id

    async def get_metadata(self) -> dict[str, Any]:
        """Return the parsed YAML frontmatter for this skill.

        Always contains the required ``name`` and ``description`` keys.
        May also include optional keys such as ``license``,
        ``compatibility``, ``metadata``, and ``allowed-tools``.

        Returns:
            Dictionary of frontmatter key-value pairs.
        """
        return await self._provider.get_metadata(self._skill_id)

    async def get_body(self) -> str:
        """Return the markdown instruction body for this skill.

        This represents the full skill instructions that an agent reads
        upon activation -- the content after the YAML frontmatter in
        the Agent Skills format.

        Returns:
            Markdown text.
        """
        return await self._provider.get_body(self._skill_id)

    async def get_outline(self) -> SkillOutline:
        """Return the body's sections without returning the body.

        Computed on top of :meth:`get_body`, which providers already
        cache, so this costs no extra round-trip on a warm provider and
        needs nothing from the :class:`~agentskills_core.SkillProvider`
        interface.

        Returns:
            A :class:`~agentskills_core.SkillOutline` carrying one
            :class:`~agentskills_core.SectionRef` per heading, the
            whole body's estimated size, and whether fetching that
            whole body is the cheaper move.
        """
        return outline_of(self._skill_id, await self.get_body())

    async def get_section(self, key: str) -> str:
        """Return one section of the body, addressed by key.

        Args:
            key: A key from :meth:`get_outline`.

        Returns:
            The heading line and everything up to the next heading of
            any level.  Sections do not overlap, so a parent does not
            include its subsections.

        Raises:
            SectionNotFoundError: If no section carries that key.
        """
        sections = split_sections(await self.get_body())
        for section in sections:
            if section.key == key:
                return section.text
        known = ", ".join(section.key for section in sections) or "none"
        raise SectionNotFoundError(
            f"Skill '{self._skill_id}' has no section '{key}'; available keys: {known}"
        )

    async def get_script(self, name: str) -> bytes:
        """Return the raw content of a bundled script.

        Args:
            name: Name of the script to retrieve.

        Returns:
            Raw content bytes.

        Raises:
            ResourceNotFoundError: If the script does not exist.
        """
        return await self._provider.get_script(self._skill_id, name)

    async def get_asset(self, name: str) -> bytes:
        """Return the raw content of a bundled asset.

        Args:
            name: Name of the asset to retrieve.

        Returns:
            Raw content bytes.

        Raises:
            ResourceNotFoundError: If the asset does not exist.
        """
        return await self._provider.get_asset(self._skill_id, name)

    async def get_reference(self, name: str) -> bytes:
        """Return the raw content of a bundled reference document.

        Args:
            name: Name of the reference to retrieve.

        Returns:
            Raw content bytes.

        Raises:
            ResourceNotFoundError: If the reference does not exist.
        """
        return await self._provider.get_reference(self._skill_id, name)

    @property
    def supports_resource_listing(self) -> bool:
        """Whether the backing provider can enumerate this skill's resources."""
        return self._provider.supports_resource_listing

    async def list_resources(self) -> dict[str, list[str]]:
        """Return this skill's resource names, grouped by kind.

        Check :attr:`supports_resource_listing` first -- not every
        backend can enumerate.

        Returns:
            Mapping of ``"references"`` / ``"scripts"`` / ``"assets"`` to
            sorted resource names.

        Raises:
            ResourceListingNotSupportedError: If the provider cannot
                enumerate resources.
        """
        return await self._provider.list_resources(self._skill_id)

    def __repr__(self) -> str:
        return f"Skill({self._skill_id!r})"
