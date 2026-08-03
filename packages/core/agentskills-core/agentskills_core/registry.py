"""Unified skill index with explicit registration.

The :class:`SkillRegistry` is the main entry-point for agent code that
needs to access Agent Skills.  Skills are registered explicitly by the
application developer using :meth:`SkillRegistry.register`, which maps
a skill ID to a :class:`~agentskills_core.Skill` handle backed by the
given provider.  Backends that can enumerate themselves can be
registered wholesale with :meth:`SkillRegistry.register_all`.

Example::

    from agentskills_core import SkillRegistry
    from agentskills_fs import LocalFileSystemSkillProvider

    provider = LocalFileSystemSkillProvider(Path("./skills"))
    registry = SkillRegistry()
    await registry.register_all(provider)

    skill = registry.get_skill("incident-response")
    meta = await skill.get_metadata()
    print(meta["description"])
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal, overload
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from agentskills_core.exceptions import SkillNotFoundError
from agentskills_core.logging import get_logger
from agentskills_core.provider import SkillProvider
from agentskills_core.skill import Skill
from agentskills_core.validation import validate_skill

_logger = get_logger(__name__)

#: Metadata fetches issued in parallel when building a catalog.
DEFAULT_CATALOG_CONCURRENCY = 8


class SkillRegistry:
    """Unified index over explicitly registered skills.

    Skills are added via :meth:`register`, either one at a time or as a
    batch of ``(skill_id, provider)`` tuples, or via :meth:`register_all`
    for a provider that can enumerate itself.  The registry enforces a
    **flat namespace**: each skill ID must be unique.  A :exc:`ValueError`
    is raised if a duplicate is detected.

    :meth:`register` is ``async`` because it validates every skill
    against the Agent Skills specification before storing it.
    :meth:`list_skills` and :meth:`get_skill` are synchronous lookups.
    :meth:`list_skills` returns :class:`~agentskills_core.Skill`
    instances sorted by ID.
    :meth:`get_skills_catalog` is ``async`` because it fetches metadata from
    providers.
    """

    def __init__(self, *, catalog_concurrency: int = DEFAULT_CATALOG_CONCURRENCY) -> None:
        """Create an empty registry.

        Args:
            catalog_concurrency: Maximum number of provider metadata
                fetches issued in parallel by :meth:`get_skills_catalog`.

        Raises:
            ValueError: If *catalog_concurrency* is less than 1.
        """
        if catalog_concurrency < 1:
            raise ValueError("catalog_concurrency must be at least 1")
        self._skills: dict[str, Skill] = {}
        self._catalog_concurrency = catalog_concurrency

    def __repr__(self) -> str:
        n = len(self._skills)
        label = "skill" if n == 1 else "skills"
        return f"SkillRegistry({n} {label})"

    @overload
    async def register(self, skill_id: str, provider: SkillProvider) -> None: ...

    @overload
    async def register(self, skills: list[tuple[str, SkillProvider]]) -> None: ...

    async def register(
        self,
        skill_id_or_skills: str | list[tuple[str, SkillProvider]],
        provider: SkillProvider | None = None,
    ) -> None:
        """Register one or more skills with their providers.

        Validates each skill against the Agent Skills specification
        using :func:`~agentskills_core.validate_skill`.  This catches
        misconfiguration (missing ``SKILL.md``, unreachable endpoint,
        invalid metadata) at registration time rather than at first use.

        **Single skill**::

            await registry.register("incident-response", provider)

        **Batch registration**::

            await registry.register([
                ("incident-response", fs_provider),
                ("api-style-guide", http_provider),
            ])

        Batch registration is **atomic** — if any skill fails
        validation, none of the skills in the batch are registered.

        Args:
            skill_id_or_skills: Either a single skill ID ``str``, or a
                ``list`` of ``(skill_id, provider)`` tuples for batch
                registration.
            provider: The :class:`~agentskills_core.SkillProvider` for
                the skill.  Required when registering a single skill;
                must be omitted for batch registration.

        Raises:
            ValueError: If a *skill_id* is already registered, if a
                skill fails validation, or if the arguments are invalid.
        """
        if isinstance(skill_id_or_skills, str):
            if provider is None:
                raise ValueError("provider is required when registering a single skill")
            await self._register_one(skill_id_or_skills, provider)
        elif isinstance(skill_id_or_skills, list):
            if provider is not None:
                raise ValueError(
                    "provider must not be passed when registering a batch — "
                    "include providers in the list of tuples instead"
                )
            await self._register_batch(skill_id_or_skills)
        else:
            raise ValueError("Expected a skill_id string or a list of (skill_id, provider) tuples")

    async def _register_one(self, skill_id: str, provider: SkillProvider) -> None:
        """Validate and register a single skill."""
        if skill_id in self._skills:
            raise ValueError(f"Duplicate skill_id '{skill_id}' -- already registered")
        validated = await self._validate_all([(skill_id, provider)])
        self._skills[skill_id] = validated[0][1]
        _logger.info("Registered skill %r from %s", skill_id, type(provider).__name__)

    async def _register_batch(self, skills: list[tuple[str, SkillProvider]]) -> None:
        """Validate and register a batch of skills atomically."""
        # Check for duplicates against existing registry and within the batch.
        seen: set[str] = set()
        for skill_id, _ in skills:
            if skill_id in self._skills:
                raise ValueError(f"Duplicate skill_id '{skill_id}' -- already registered")
            if skill_id in seen:
                raise ValueError(f"Duplicate skill_id '{skill_id}' within the batch")
            seen.add(skill_id)

        validated = await self._validate_all(skills)

        # All passed -- commit.
        for skill_id, skill in validated:
            self._skills[skill_id] = skill
        _logger.info("Registered %d skills: %s", len(validated), [sid for sid, _ in validated])

    async def register_all(self, provider: SkillProvider) -> list[str]:
        """Register every skill a provider holds.

        Asks the provider to enumerate itself and registers the result,
        so a folder of thirty skills does not require thirty hard-coded
        identifiers::

            provider = LocalFileSystemSkillProvider(Path("./skills"))
            registered = await registry.register_all(provider)

        Discovery is an **optional capability**.  Providers that cannot
        enumerate raise rather than returning an empty list, so a
        misconfigured backend cannot look like an empty one -- check
        :attr:`SkillProvider.supports_discovery
        <agentskills_core.SkillProvider.supports_discovery>` first if
        the provider may not support it.

        Registration is **atomic** and reports every validation failure
        at once.  Discovering thirty skills and being told only about
        the first broken one turns a single fix into thirty rounds.

        Args:
            provider: The backend to enumerate and register.

        Returns:
            The registered skill IDs, sorted.

        Raises:
            DiscoveryNotSupportedError: If *provider* cannot enumerate
                the skills it holds.
            ValueError: If any discovered ID is already registered, or
                if any discovered skill fails validation.  Nothing is
                registered in either case.
        """
        skill_ids = await provider.discover()

        clashes = [skill_id for skill_id in skill_ids if skill_id in self._skills]
        if clashes:
            raise ValueError(
                f"{type(provider).__name__} discovered skills that are already "
                f"registered: {', '.join(sorted(clashes))}"
            )

        validated = await self._validate_all([(skill_id, provider) for skill_id in skill_ids])

        # All passed -- commit.
        for skill_id, skill in validated:
            self._skills[skill_id] = skill
        _logger.info(
            "Registered %d discovered skills from %s",
            len(validated),
            type(provider).__name__,
        )
        return sorted(skill_id for skill_id, _ in validated)

    async def _validate_all(
        self, skills: list[tuple[str, SkillProvider]]
    ) -> list[tuple[str, Skill]]:
        """Validate every skill, reporting all failures in one error.

        Stopping at the first failure would make fixing a batch an
        iterative game of whack-a-mole.
        """
        validated: list[tuple[str, Skill]] = []
        failures: list[str] = []
        for skill_id, provider in skills:
            skill = Skill(skill_id=skill_id, provider=provider)
            errors = await validate_skill(skill)
            if errors:
                failures.append(
                    f"Skill '{skill_id}' failed validation:\n"
                    + "\n".join(f"  - {e}" for e in errors)
                )
            else:
                validated.append((skill_id, skill))
        if failures:
            raise ValueError("\n".join(failures))
        return validated

    def list_skills(self) -> list[Skill]:
        """Return registered skills sorted by ID.

        Returns:
            Alphabetically sorted list of :class:`~agentskills_core.Skill`
            instances.  Use :meth:`Skill.get_id` to obtain a skill's name.
        """
        return sorted(self._skills.values(), key=lambda s: s.get_id())

    def get_skill(self, skill_id: str) -> Skill:
        """Return the :class:`~agentskills_core.Skill` handle by name.

        Args:
            skill_id: Skill name to look up.

        Returns:
            The registered :class:`~agentskills_core.Skill` instance.

        Raises:
            SkillNotFoundError: If no skill with the given name is registered.
        """
        try:
            return self._skills[skill_id]
        except KeyError:
            raise SkillNotFoundError(f"Skill '{skill_id}' not found in registry") from None

    async def get_skills_catalog(
        self,
        *,
        format: Literal["xml", "markdown"] = "xml",
    ) -> str:
        """Build a skill-catalog string for system-prompt injection.

        Two output formats are supported:

        ``"xml"``
            An ``<available_skills>`` XML block.  This is the
            **recommended** format when using Claude or other
            Anthropic models.

        ``"markdown"``
            A human-readable Markdown catalog listing every registered
            skill's name and description.

        Only ``name`` and ``description`` are extracted from each
        skill's metadata, keeping token usage low.

        Args:
            format: Output format — ``"xml"`` (default) or ``"markdown"``.

        Returns:
            A string ready for insertion into a system prompt.

        Raises:
            ValueError: If *format* is not ``"xml"`` or ``"markdown"``.
        """
        if format == "xml":
            return await self._build_xml()
        if format == "markdown":
            return await self._build_markdown()
        msg = f"Unsupported format {format!r}; expected 'xml' or 'markdown'."
        raise ValueError(msg)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _gather_metadata(self) -> list[tuple[Skill, dict[str, Any]]]:
        """Fetch metadata for every registered skill concurrently.

        Ordering follows :meth:`list_skills` regardless of completion
        order, so catalog output is deterministic.
        """
        skills = self.list_skills()
        semaphore = asyncio.Semaphore(self._catalog_concurrency)

        async def fetch(skill: Skill) -> dict[str, Any]:
            async with semaphore:
                try:
                    return await skill.get_metadata()
                except Exception as exc:
                    exc.add_note(f"raised while building the catalog entry for '{skill.get_id()}'")
                    raise

        metadata = await asyncio.gather(*(fetch(skill) for skill in skills))
        _logger.debug(
            "Gathered catalog metadata for %d skills at concurrency %d",
            len(skills),
            self._catalog_concurrency,
        )
        return list(zip(skills, metadata, strict=True))

    async def _build_xml(self) -> str:
        """Return an ``<available_skills>`` XML block."""
        entries = await self._gather_metadata()
        if not entries:
            return "<available_skills />"

        root = Element("available_skills")
        for skill, meta in entries:
            skill_el = SubElement(root, "skill")
            name_el = SubElement(skill_el, "name")
            name_el.text = meta.get("name", skill.get_id())
            desc_el = SubElement(skill_el, "description")
            desc_el.text = meta.get("description", "")
            version = meta.get("version")
            if version:
                # Omitted when absent so unversioned skills cost no prompt tokens.
                version_el = SubElement(skill_el, "version")
                version_el.text = str(version)
        indent(root, space="  ")
        return tostring(root, encoding="unicode")

    async def _build_markdown(self) -> str:
        """Return a Markdown-formatted skill catalog."""
        entries = await self._gather_metadata()
        if not entries:
            return "No skills are currently available."

        lines: list[str] = [
            "# Available Skills",
            "",
        ]

        for skill, meta in entries:
            name = meta.get("name", skill.get_id())
            description = meta.get("description", "No description available.")

            lines.append(f"## {name}")
            lines.append(f"- **Description**: {description}")
            version = meta.get("version")
            if version:
                lines.append(f"- **Version**: {version}")
            lines.append("")

        return "\n".join(lines)
