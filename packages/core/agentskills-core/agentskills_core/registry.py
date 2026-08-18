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
from collections.abc import Callable, Iterable
from functools import partial
from typing import Any, Literal, overload
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from agentskills_core.exceptions import SkillNotFoundError
from agentskills_core.logging import get_logger
from agentskills_core.provider import SkillProvider
from agentskills_core.skill import Skill
from agentskills_core.validation import SELECTION_FIELDS, validate_skill

_logger = get_logger(__name__)

#: Metadata fetches issued in parallel when building a catalog.
DEFAULT_CATALOG_CONCURRENCY = 8

#: Key under the spec's free-form ``metadata`` mapping holding a skill's tags.
TAGS_METADATA_KEY = "tags"

#: Markdown bullet labels for the selection-metadata fields.
_MARKDOWN_SELECTION_LABELS = {
    "when_to_use": "When to use",
    "when_not_to_use": "When not to use",
}


def _cases_of(skill_id: str, meta: dict[str, Any], key: str) -> list[str]:
    """Return one selection-metadata list, or empty when unusable.

    Registration validates these fields, so a bad value here means the
    catalog is being built over metadata that never passed through
    :meth:`SkillRegistry.register`.  Warn and drop rather than raise: a
    malformed hint should cost a skill its hint, not its place in the
    catalog.
    """
    raw = meta.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(case, str) for case in raw):
        _logger.warning(
            "Skill '%s': '%s' is not a list of strings; omitting it from the catalog",
            skill_id,
            key,
        )
        return []
    return [case for case in raw if case.strip()]


def _tags_of(skill_id: str, meta: dict[str, Any]) -> frozenset[str]:
    """Return a skill's tags, case-folded, from ``metadata.tags``.

    The Agent Skills spec already defines ``metadata`` as a free-form
    mapping, so tags live there rather than in a new top-level field
    this project would have to defend upstream.
    """
    container = meta.get("metadata")
    if not isinstance(container, dict):
        return frozenset()
    raw = container.get(TAGS_METADATA_KEY)
    if raw is None:
        return frozenset()
    if not isinstance(raw, list) or not all(isinstance(tag, str) for tag in raw):
        _logger.warning(
            "Skill '%s': metadata.%s must be a list of strings; ignoring it for filtering",
            skill_id,
            TAGS_METADATA_KEY,
        )
        return frozenset()
    return frozenset(tag.strip().casefold() for tag in raw if tag.strip())


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
        tags: Iterable[str] | None = None,
        include: Iterable[str] | None = None,
        exclude: Iterable[str] | None = None,
        max_chars: int | None = None,
        selection_hints: bool = True,
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

        Only ``name``, ``description`` and the selection metadata are
        extracted from each skill's metadata, keeping token usage low.

        The catalog is injected into every system prompt on every turn,
        so its size is a fixed cost per request.  The filters below
        narrow it, and *max_chars* caps it::

            await registry.get_skills_catalog(
                tags=["incident"],
                exclude=["deprecated-runbook"],
                max_chars=8000,
            )

        *include* and *exclude* match skill IDs and are applied before
        any metadata is fetched, so narrowing a large registry costs
        proportionally fewer provider round-trips.  *tags* needs
        metadata and is applied after.

        Args:
            format: Output format — ``"xml"`` (default) or ``"markdown"``.
            tags: Keep only skills carrying at least one of these tags,
                read from the spec's free-form ``metadata`` mapping
                under ``tags``.  Matching is case-insensitive.  A skill
                with no tags matches no tag filter.
            include: Allow-list of skill IDs.  Only these are
                considered.  An ID that is not registered raises, since
                an allow-list naming a skill that does not exist
                silently costs the agent a capability.
            exclude: Deny-list of skill IDs, applied after *include* and
                winning over it — a deny-list that another argument can
                override is not a deny-list.  Unregistered IDs are
                ignored here, because a deny-list is meant to outlive
                the thing it denies.
            max_chars: Hard ceiling on the length of the returned
                string, including the truncation note.  Whole entries
                are dropped from the end until the result fits, so the
                output stays valid and the same arguments always
                produce the same catalog.  Roughly four characters per
                token is the usual estimate.
            selection_hints: Include each skill's ``when_to_use`` and
                ``when_not_to_use`` entries.  They make selection more
                accurate and they are charged on every turn, so pass
                ``False`` to trade that accuracy back for tokens.  The
                result is then byte-identical to a catalog built from
                skills that declare neither field.

        Returns:
            A string ready for insertion into a system prompt.  When
            entries were dropped, the XML root carries ``truncated``,
            ``shown`` and ``total`` attributes and the Markdown gains a
            closing note; nothing is ever dropped silently, because a
            catalog that varies without saying so makes agent behaviour
            non-reproducible.

        Raises:
            ValueError: If *format* is not ``"xml"`` or ``"markdown"``,
                or if *max_chars* is too small to hold even an empty
                catalog and its note.
            SkillNotFoundError: If *include* names an unregistered skill.
        """
        if format == "xml":
            render = self._render_xml
        elif format == "markdown":
            render = self._render_markdown
        else:
            msg = f"Unsupported format {format!r}; expected 'xml' or 'markdown'."
            raise ValueError(msg)
        render = partial(render, selection_hints=selection_hints)

        # No catalog cache exists yet. When one is added, its key must
        # cover the format and every filter argument below.
        entries = await self._gather_metadata(self._select(include, exclude))
        if tags is not None:
            wanted = {tag.strip().casefold() for tag in tags if tag.strip()}
            entries = [
                (skill, meta) for skill, meta in entries if wanted & _tags_of(skill.get_id(), meta)
            ]

        return self._fit(entries, max_chars, render)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _select(self, include: Iterable[str] | None, exclude: Iterable[str] | None) -> list[Skill]:
        """Apply the ID filters, which need no metadata."""
        skills = self.list_skills()

        if include is not None:
            wanted = set(include)
            missing = sorted(wanted - self._skills.keys())
            if missing:
                raise SkillNotFoundError(
                    f"include names skills that are not registered: {', '.join(missing)}"
                )
            skills = [skill for skill in skills if skill.get_id() in wanted]

        if exclude is not None:
            unwanted = set(exclude)
            skills = [skill for skill in skills if skill.get_id() not in unwanted]

        return skills

    @staticmethod
    def _fit(
        entries: list[tuple[Skill, dict[str, Any]]],
        max_chars: int | None,
        render: Callable[[list[tuple[Skill, dict[str, Any]]], int], str],
    ) -> str:
        """Drop trailing entries until the rendered catalog fits.

        Re-rendering after each drop measures the real thing.  A length
        model would have to predict XML escaping and Markdown joining,
        and be corrected every time either renderer changes.
        """
        total = len(entries)
        shown = total
        while True:
            text = render(entries[:shown], total)
            if max_chars is None or len(text) <= max_chars:
                return text
            if shown == 0:
                raise ValueError(
                    f"max_chars={max_chars} cannot hold the smallest possible "
                    f"catalog, which needs {len(text)} characters."
                )
            shown -= 1

    async def _gather_metadata(self, skills: list[Skill]) -> list[tuple[Skill, dict[str, Any]]]:
        """Fetch metadata for the given skills concurrently.

        Ordering follows the input regardless of completion order, so
        catalog output is deterministic.
        """
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

    @staticmethod
    def _render_xml(
        entries: list[tuple[Skill, dict[str, Any]]],
        total: int,
        *,
        selection_hints: bool = True,
    ) -> str:
        """Return an ``<available_skills>`` XML block."""
        root = Element("available_skills")
        if len(entries) < total:
            root.set("truncated", "true")
            root.set("shown", str(len(entries)))
            root.set("total", str(total))

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
            if selection_hints:
                for key in SELECTION_FIELDS:
                    cases = _cases_of(skill.get_id(), meta, key)
                    if not cases:
                        continue
                    field_el = SubElement(skill_el, key)
                    for case in cases:
                        case_el = SubElement(field_el, "case")
                        case_el.text = case
        indent(root, space="  ")
        return tostring(root, encoding="unicode")

    @staticmethod
    def _render_markdown(
        entries: list[tuple[Skill, dict[str, Any]]],
        total: int,
        *,
        selection_hints: bool = True,
    ) -> str:
        """Return a Markdown-formatted skill catalog."""
        truncated = len(entries) < total
        if not entries:
            base = "No skills are currently available."
            if not truncated:
                return base
            return f"{base}\n\n_Catalog truncated: showing 0 of {total} skills._"

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
            if selection_hints:
                for key, label in _MARKDOWN_SELECTION_LABELS.items():
                    cases = _cases_of(skill.get_id(), meta, key)
                    if not cases:
                        continue
                    lines.append(f"- **{label}**:")
                    lines.extend(f"  - {case}" for case in cases)
            lines.append("")

        if truncated:
            lines.append(f"_Catalog truncated: showing {len(entries)} of {total} skills._")

        return "\n".join(lines)
