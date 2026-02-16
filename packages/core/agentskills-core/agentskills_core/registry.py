"""Unified skill index with explicit registration.

The :class:`SkillRegistry` is the main entry-point for agent code that
needs to access Agent Skills.  Skills are registered explicitly by the
application developer using :meth:`SkillRegistry.register`, which maps
a skill ID to a :class:`~agentskills_core.Skill` handle backed by the
given provider.

Example::

    from agentskills_core import SkillRegistry
    from agentskills_fs import LocalFileSystemSkillProvider

    provider = LocalFileSystemSkillProvider(Path("./skills"))
    registry = SkillRegistry()
    await registry.register("incident-response", provider)

    skill = registry.get_skill("incident-response")
    meta = await skill.get_metadata()
    print(meta["description"])
"""

from __future__ import annotations

from typing import Literal, overload
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from agentskills_core.exceptions import SkillNotFoundError
from agentskills_core.provider import SkillProvider
from agentskills_core.skill import Skill
from agentskills_core.validation import validate_skill


class SkillRegistry:
    """Unified index over explicitly registered skills.

    Skills are added via :meth:`register`, either one at a time or as a
    batch of ``(skill_id, provider)`` tuples.  The registry enforces a
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

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

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
        skill = Skill(skill_id=skill_id, provider=provider)
        errors = await validate_skill(skill)
        if errors:
            raise ValueError(
                f"Skill '{skill_id}' failed validation:\n" + "\n".join(f"  - {e}" for e in errors)
            )
        self._skills[skill_id] = skill

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

        # Validate all skills first.
        validated: list[tuple[str, Skill]] = []
        for skill_id, prov in skills:
            skill = Skill(skill_id=skill_id, provider=prov)
            errors = await validate_skill(skill)
            if errors:
                raise ValueError(
                    f"Skill '{skill_id}' failed validation:\n"
                    + "\n".join(f"  - {e}" for e in errors)
                )
            validated.append((skill_id, skill))

        # All passed — commit.
        for skill_id, skill in validated:
            self._skills[skill_id] = skill

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

    async def _build_xml(self) -> str:
        """Return an ``<available_skills>`` XML block."""
        skills = self.list_skills()
        if not skills:
            return "<available_skills />"

        root = Element("available_skills")
        for skill in skills:
            meta = await skill.get_metadata()
            skill_el = SubElement(root, "skill")
            name_el = SubElement(skill_el, "name")
            name_el.text = meta.get("name", skill.get_id())
            desc_el = SubElement(skill_el, "description")
            desc_el.text = meta.get("description", "")
        indent(root, space="  ")
        return tostring(root, encoding="unicode")

    async def _build_markdown(self) -> str:
        """Return a Markdown-formatted skill catalog."""
        skills = self.list_skills()
        if not skills:
            return "No skills are currently available."

        lines: list[str] = [
            "# Available Skills",
            "",
        ]

        for skill in skills:
            meta = await skill.get_metadata()

            name = meta.get("name", skill.get_id())
            description = meta.get("description", "No description available.")

            lines.append(f"## {name}")
            lines.append(f"- **Description**: {description}")
            lines.append("")

        return "\n".join(lines)
