"""Convert common agent instruction files into ``agentskills-core`` objects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agentskills_core import ResourceNotFoundError, Skill, SkillProvider

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_SUPPORTED_FILES = {"AGENTS.md", "copilot-instructions.md"}
_RESOURCE_KINDS = ("references", "scripts", "assets")


@dataclass(frozen=True)
class ImportedSkill:
    """A native ``Skill`` plus the source and rendered ``SKILL.md`` text."""

    skill: Skill
    source: Path
    skill_md: str


class _ImportedProvider(SkillProvider):
    """Serve one imported skill from immutable in-memory content."""

    def __init__(self, metadata: dict[str, Any], body: str) -> None:
        self._metadata = metadata
        self._body = body

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        return self._metadata.copy()

    async def get_body(self, skill_id: str) -> str:
        return self._body

    async def get_script(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(f"Imported skill has no scripts: {name!r}")

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(f"Imported skill has no assets: {name!r}")

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(f"Imported skill has no references: {name!r}")


def _slug(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.lower())
    return "-".join(words)[:64].strip("-") or "imported-skill"


def _heading(text: str) -> str | None:
    for line in text.splitlines():
        match = _HEADING.match(line.strip())
        if match:
            return match.group(1).strip()
    return None


def _description(source: Path, body: str, explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    heading = _heading(body)
    if heading:
        return f"Imported instructions for {heading}."
    return f"Imported instructions from {source.name}."


def _parse_source(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    metadata = yaml.safe_load(match.group(1)) or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"frontmatter in {path} must be a mapping")
    return metadata, match.group(2)


def _metadata(path: Path, raw: dict[str, Any], body: str, name: str | None) -> dict[str, Any]:
    title = _heading(body) or path.stem
    skill_name = _slug(name or raw.get("name") or title)
    metadata: dict[str, Any] = {
        "name": skill_name,
        "description": _description(path, body, raw.get("description")),
    }
    if path.suffix.lower() == ".mdc" and raw.get("globs") is not None:
        metadata["metadata"] = {"globs": raw["globs"], "source": "cursor"}
    for key in ("license", "compatibility", "allowed-tools", "version"):
        if key in raw:
            metadata[key] = raw[key]
    return metadata


def _render(metadata: dict[str, Any], body: str) -> str:
    frontmatter = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=False).strip()
    return f"---\n{frontmatter}\n---\n\n{body.lstrip()}"


def adapt_path(
    path: str | Path, *, name: str | None = None, description: str | None = None
) -> ImportedSkill:
    """Adapt one supported file or Claude-style skill directory.

    Args:
        path: An ``AGENTS.md``, Copilot instructions file, Cursor ``.mdc``
            rule, or directory containing ``SKILL.md``.
        name: Optional native skill name override.
        description: Optional explicit catalog description.

    Returns:
        Imported skill handle, source path, and native ``SKILL.md`` text.

    Raises:
        ValueError: If the source shape is unsupported or metadata is invalid.
    """
    source = Path(path).expanduser().resolve()
    if source.is_dir():
        source = source / "SKILL.md"
    if not source.is_file():
        raise ValueError(f"unsupported adapter source: {path}")
    if source.name not in _SUPPORTED_FILES and source.suffix.lower() not in {".mdc", ".md"}:
        raise ValueError(f"unsupported adapter source: {path}")

    raw, body = _parse_source(source)
    metadata = _metadata(source, raw, body, name)
    if description:
        metadata["description"] = _description(source, body, description)
    rendered = _render(metadata, body)
    provider = _ImportedProvider(metadata, body)
    return ImportedSkill(Skill(metadata["name"], provider), source, rendered)


def discover_sources(root: str | Path) -> list[Path]:
    """Find supported instruction sources below *root* without duplicates."""
    base = Path(root).expanduser().resolve()
    candidates: set[Path] = set()
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if path.name in _SUPPORTED_FILES or path.suffix.lower() == ".mdc":
            candidates.add(path)
    for path in base.rglob("SKILL.md"):
        candidates.add(path)
    return sorted(candidates)


def render_skill_md(imported: ImportedSkill) -> str:
    """Return the native ``SKILL.md`` text for an imported skill."""
    return imported.skill_md
