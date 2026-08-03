"""Abstract interface for skill content retrieval.

This module defines :class:`SkillProvider`, the abstract base class that all
skill backends must implement.  The interface follows the progressive-disclosure
model described in the `Agent Skills specification
<https://agentskills.io/specification>`_:

1. **Metadata** -- retrieve the frontmatter key-value pairs.
2. **Activation** -- load the full instruction body on demand.
3. **Resources** -- serve scripts, references, and assets only when requested.

A provider is a **content accessor**: given a skill ID it serves metadata,
body, and resources.  Backends that can enumerate what they hold may also
implement :meth:`SkillProvider.discover`, which
:meth:`SkillRegistry.register_all <agentskills_core.SkillRegistry.register_all>`
uses to register a whole backend at once.  Where that is not possible,
registration stays explicit via
:meth:`SkillRegistry.register(skill_id, provider)
<agentskills_core.SkillRegistry.register>`.

Resource *names* may be discovered two ways: from the skill body (the
markdown instructions), or -- where the backend supports it -- from
:meth:`SkillProvider.list_resources`.  Listing and discovery are both
**optional capabilities**: backends that cannot enumerate (a static HTTP
host with no manifest, say) leave the corresponding ``supports_*``
attribute ``False`` and the default implementation refuses.  See
:doc:`ADR 0002 </adr/0002-optional-provider-capabilities>`.

All methods are ``async`` so that implementations backed by network I/O
(HTTP APIs, databases, cloud storage) can be non-blocking.  Filesystem
implementations may use synchronous I/O inside ``async def`` methods
when file sizes are small.

Concrete implementations include
:class:`~agentskills_fs.LocalFileSystemSkillProvider` for local directory trees.
"""

from abc import ABC, abstractmethod
from typing import Any

from agentskills_core.exceptions import (
    DiscoveryNotSupportedError,
    ResourceListingNotSupportedError,
)

#: Resource categories defined by the Agent Skills specification.
RESOURCE_KINDS: tuple[str, ...] = ("references", "scripts", "assets")


class SkillProvider(ABC):
    """Abstract base class that every skill backend must implement.

    A :class:`SkillProvider` is a pure content accessor -- it serves
    skill metadata, body text, and resources by skill ID.  Enumerating
    the skills a backend holds is an optional capability: see
    :meth:`discover`.  Without it, registration is explicit via
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

    #: Whether this provider can enumerate a skill's resources.  Set to
    #: ``True`` by implementations that override :meth:`list_resources`.
    #: Declared as a plain attribute rather than a ``ClassVar`` so that
    #: providers whose capability depends on configuration can set it
    #: per instance.
    supports_resource_listing: bool = False

    #: Whether this provider can enumerate the skills it holds.  Set to
    #: ``True`` by implementations that override :meth:`discover`.  Also
    #: a plain attribute, for the same reason.
    supports_discovery: bool = False

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

        The returned dict must not be shared between calls: a caller that
        mutates it must not affect the next caller.  Implementations that
        cache a parsed dict should return a copy.

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

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        """Return the resource names a skill contains, grouped by kind.

        **Optional capability.**  The default implementation refuses.
        Override it *and* set :attr:`supports_resource_listing` to
        ``True`` in backends that can enumerate.

        Implementations return every key in :data:`RESOURCE_KINDS`, using
        an empty list for a category the skill does not use, so callers
        never have to guard on key presence.  Names are sorted.

        Args:
            skill_id: The skill name to enumerate.

        Returns:
            Mapping of ``"references"`` / ``"scripts"`` / ``"assets"`` to
            sorted resource names.

        Raises:
            ResourceListingNotSupportedError: If this provider cannot
                enumerate resources.  Never returns an empty mapping to
                signal the same thing -- that would be indistinguishable
                from a skill with no resources.
            SkillNotFoundError: If the skill does not exist.
        """
        raise ResourceListingNotSupportedError(
            f"{type(self).__name__} cannot enumerate skill resources. "
            f"Resource names must be taken from the skill body instead."
        )

    async def discover(self) -> list[str]:
        """Return the IDs of every skill this provider can serve.

        **Optional capability.**  The default implementation refuses.
        Override it *and* set :attr:`supports_discovery` to ``True`` in
        backends that can enumerate.

        Implementations return sorted IDs, and return only skills that
        appear to exist -- a directory without a ``SKILL.md`` is not a
        skill.  Discovery does **not** validate: an ID that comes back
        here can still fail :func:`~agentskills_core.validate_skill`,
        which is what :meth:`SkillRegistry.register_all
        <agentskills_core.SkillRegistry.register_all>` reports on.

        Returns:
            Sorted skill IDs.  An empty list means the backend was
            enumerated and holds nothing.

        Raises:
            DiscoveryNotSupportedError: If this provider cannot
                enumerate its skills.  Never returns an empty list to
                signal the same thing -- that would be indistinguishable
                from an empty backend, and would silently register
                nothing.
        """
        raise DiscoveryNotSupportedError(
            f"{type(self).__name__} cannot enumerate the skills it holds. "
            f"Register skills explicitly with registry.register(skill_id, provider)."
        )
