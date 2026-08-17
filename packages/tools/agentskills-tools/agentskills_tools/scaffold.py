"""``agentskills init`` — scaffold a skill that already validates.

The template is checked against :func:`~agentskills_core.validate_skill`
before anything is written to disk.  That both rejects a bad skill name
without duplicating the specification's rules here, and guarantees the
template we ship cannot itself drift out of conformance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentskills_adapters import adapt_path
from agentskills_adapters import render_skill_md as render_imported_skill_md
from agentskills_core import (
    ResourceNotFoundError,
    Skill,
    SkillProvider,
    get_logger,
    validate_skill,
)
from agentskills_tools.discovery import SKILL_FILE, CliError

RESOURCE_DIRS = ("references", "scripts", "assets")

DEFAULT_DESCRIPTION = "One sentence on what this skill does and when an agent should reach for it."

_FRONTMATTER = """---
name: {name}
description: {description}
version: 0.1.0
---

"""

_BODY = """# {title}

## When to use this

Describe the situation that should make an agent load this skill.

## Steps

1. First step.
2. Second step.

## References

Point at files in `references/` so they load only when they are needed.
"""

_logger = get_logger(__name__)


class _TemplateProvider(SkillProvider):
    """Serves the unwritten template so it can be validated in memory."""

    def __init__(self, metadata: dict[str, Any], body: str) -> None:
        self._metadata = metadata
        self._body = body

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        return self._metadata

    async def get_body(self, skill_id: str) -> str:
        return self._body

    async def get_script(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(f"Template has no scripts: {name!r}")

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(f"Template has no assets: {name!r}")

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(f"Template has no references: {name!r}")


def render_body(name: str) -> str:
    """Return the markdown body for a new skill."""
    return _BODY.format(title=name.replace("-", " ").title())


def render_skill_md(name: str, description: str) -> str:
    """Return the full ``SKILL.md`` text for a new skill."""
    return _FRONTMATTER.format(name=name, description=description) + render_body(name)


async def init_skill(name: str, parent: Path, description: str = DEFAULT_DESCRIPTION) -> Path:
    """Create a new skill directory under *parent*.

    Args:
        name: Skill name, which is also the directory name.
        parent: Directory to create the skill in.
        description: Frontmatter description for the new skill.

    Returns:
        The path of the created skill directory.

    Raises:
        CliError: If the name would not validate, if the skill already
            exists, or if the directory cannot be written.
    """
    if not name.strip():
        raise CliError("skill name must not be empty")

    body = render_body(name)
    metadata = {"name": name, "description": description, "version": "0.1.0"}
    errors = await validate_skill(Skill(name, _TemplateProvider(metadata, body)))
    if errors:
        prefix = f"Skill '{name}': "
        detail = "; ".join(message.removeprefix(prefix) for message in errors)
        raise CliError(f"cannot scaffold '{name}': {detail}")

    target = parent.expanduser().resolve() / name
    if (target / SKILL_FILE).exists():
        raise CliError(f"{target / SKILL_FILE} already exists")

    try:
        for resource_dir in RESOURCE_DIRS:
            (target / resource_dir).mkdir(parents=True, exist_ok=True)
        (target / SKILL_FILE).write_text(render_skill_md(name, description), encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot write to {target}: {exc}") from exc

    _logger.info("Scaffolded skill %s at %s", name, target)
    return target


async def init_from(
    source: Path,
    parent: Path,
    name: str | None = None,
    description: str | None = None,
) -> Path:
    """Convert an external instruction source into a native ``SKILL.md``."""
    try:
        imported = adapt_path(source, name=name, description=description)
        errors = await validate_skill(imported.skill)
    except (OSError, ValueError) as exc:
        raise CliError(f"cannot import {source}: {exc}") from exc
    if errors:
        raise CliError("cannot import skill: " + "; ".join(errors))

    target_name = imported.skill.get_id()
    target = parent.expanduser().resolve() / target_name
    if (target / SKILL_FILE).exists():
        raise CliError(f"{target / SKILL_FILE} already exists")
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / SKILL_FILE).write_text(render_imported_skill_md(imported), encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot write to {target}: {exc}") from exc
    _logger.info("Imported skill %s at %s", target_name, target)
    return target
