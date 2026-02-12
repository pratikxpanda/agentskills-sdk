"""Abstract interface for skill content retrieval.

This module defines :class:`SkillProvider`, the abstract base class that all
skill backends must implement.  The interface follows the progressive-disclosure
model described in the `Agent Skills specification
<https://agentskills.io/specification>`_:

1. **Metadata** -- retrieve the frontmatter key-value pairs.
2. **Activation** -- load the full instruction body on demand.
3. **Resources** -- serve scripts, references, and assets only when requested.

A provider is a **content accessor**: given a skill ID it serves metadata,
body, and resources.  It does **not** enumerate or discover skills.
Registration of skills is handled explicitly by the application via
:meth:`SkillRegistry.register(skill_id, provider)
<agentskills_core.SkillRegistry.register>`.

Resource *names* are discovered by the agent from the skill body (the
markdown instructions), not from a programmatic listing.  The provider
only needs to serve individual resources by name.

All methods are ``async`` so that implementations backed by network I/O
(HTTP APIs, databases, cloud storage) can be non-blocking.  Filesystem
implementations may use synchronous I/O inside ``async def`` methods
when file sizes are small.

Concrete implementations include
:class:`~agentskills_fs.LocalFileSystemSkillProvider` for local directory trees.
"""

from abc import ABC, abstractmethod
from typing import Any


class SkillProvider(ABC):
    """Abstract base class that every skill backend must implement.

    A :class:`SkillProvider` is a pure content accessor -- it serves
    skill metadata, body text, and resources by skill ID.  It does
    **not** enumerate or discover skills; registration is explicit via
    :meth:`SkillRegistry.register <agentskills_core.SkillRegistry.register>`.

    Implementations must enforce progressive disclosure: expensive I/O
    (reading file bodies, fetching resources) should only happen when
    the corresponding method is called explicitly.

    All methods are ``async`` to support non-blocking implementations.

    Subclass this to back skills with any storage -- filesystem, database,
    remote API, etc.  Register skills with a
    :class:`~agentskills_core.SkillRegistry` to create a unified skill
    catalog.

    Example::

        class MyProvider(SkillProvider):
            async def get_metadata(self, skill_id: str) -> dict: ...
            async def get_body(self, skill_id: str) -> str: ...
            # ... remaining abstract methods
    """

    @abstractmethod
    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        """Return the parsed YAML frontmatter for a skill.

        Per the specification the returned dict will always contain at least
        the required ``name`` and ``description`` keys.  Optional keys
        include ``license``, ``compatibility``, ``metadata``, and
        ``allowed-tools``.

        This method should return **only** the frontmatter metadata --
        never the full instruction body -- to keep context usage low
        during the discovery phase.

        Args:
            skill_id: The skill name to look up.

        Returns:
            Dictionary of frontmatter key-value pairs.

        Raises:
            SkillNotFoundError: If the skill does not exist.
        """

    @abstractmethod
    async def get_body(self, skill_id: str) -> str:
        """Return the markdown body (instructions) for a skill.

        The body contains the skill's full instructions in Markdown
        format, corresponding to the content after the YAML frontmatter
        in the Agent Skills format.  It should only be loaded when the
        agent decides to *activate* the skill (progressive disclosure).

        Args:
            skill_id: The skill name to look up.

        Returns:
            The markdown instruction text.

        Raises:
            SkillNotFoundError: If the skill does not exist.
        """

    @abstractmethod
    async def get_script(self, skill_id: str, name: str) -> bytes:
        """Return the raw bytes of a single script.

        Args:
            skill_id: The skill name containing the script.
            name: Name of the script to retrieve.

        Returns:
            Raw content as bytes.

        Raises:
            ResourceNotFoundError: If the script does not exist.
        """

    @abstractmethod
    async def get_asset(self, skill_id: str, name: str) -> bytes:
        """Return the raw bytes of a single asset.

        Args:
            skill_id: The skill name containing the asset.
            name: Name of the asset to retrieve.

        Returns:
            Raw content as bytes.

        Raises:
            ResourceNotFoundError: If the asset does not exist.
        """

    @abstractmethod
    async def get_reference(self, skill_id: str, name: str) -> bytes:
        """Return the raw bytes of a single reference document.

        Args:
            skill_id: The skill name containing the reference.
            name: Name of the reference to retrieve.

        Returns:
            Raw content as bytes.

        Raises:
            ResourceNotFoundError: If the reference does not exist.
        """
