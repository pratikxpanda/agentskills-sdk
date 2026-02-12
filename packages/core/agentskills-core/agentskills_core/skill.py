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

from agentskills_core.provider import SkillProvider


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

    def __repr__(self) -> str:
        return f"Skill({self._skill_id!r})"
