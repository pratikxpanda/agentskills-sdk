"""Canonical file manifests for the official MCP Skills extension."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import yaml

from agentskills_core.snapshots import (
    DEFAULT_SNAPSHOT_MAX_BYTES,
    DEFAULT_SNAPSHOT_MAX_FILES,
    SkillSnapshot,
    _paths,
)


class _FrontmatterLoader(yaml.SafeLoader):
    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._validated_mappings: set[int] = set()

    def flatten_mapping(self, node: yaml.MappingNode) -> None:
        if id(node) not in self._validated_mappings:
            explicit_keys: set[tuple[str, str]] = set()
            for key_node, _ in node.value:
                key = (
                    "<<"
                    if key_node.tag == "tag:yaml.org,2002:merge"
                    else self.construct_object(key_node, deep=True)
                )
                if not isinstance(key, str):
                    raise ValueError("Frontmatter mapping keys must be strings")
                identity = (key_node.tag, key)
                if identity in explicit_keys:
                    raise ValueError(f"Duplicate frontmatter key: {key}")
                explicit_keys.add(identity)
            self._validated_mappings.add(id(node))
        super().flatten_mapping(node)

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
        result = super().construct_mapping(node, deep=True)
        if not all(isinstance(key, str) for key in result):
            raise ValueError("Frontmatter mapping keys must be strings")
        return result


def _frontmatter(data: bytes) -> dict[str, Any]:
    try:
        lines = data.decode("utf-8-sig").splitlines(keepends=True)
        if not lines or lines[0].rstrip("\r\n") != "---":
            raise ValueError("SKILL.md must begin with YAML frontmatter")
        end = next(
            (index for index, line in enumerate(lines[1:], 1) if line.rstrip("\r\n") == "---"),
            None,
        )
        if end is None:
            raise ValueError("SKILL.md frontmatter is not closed")
        metadata = yaml.load("".join(lines[1:end]), Loader=_FrontmatterLoader)
        if not isinstance(metadata, dict):
            raise ValueError("SKILL.md frontmatter must be an object")
        encoded_size = 0
        for chunk in json.JSONEncoder(allow_nan=False, ensure_ascii=False).iterencode(metadata):
            encoded_size += len(chunk.encode("utf-8"))
            if encoded_size > DEFAULT_SNAPSHOT_MAX_BYTES:
                raise ValueError("Frontmatter JSON exceeds the 16 MiB publication limit")
    except (UnicodeError, yaml.YAMLError, TypeError, RecursionError) as exc:
        raise ValueError("SKILL.md frontmatter must contain UTF-8 JSON-compatible YAML") from exc
    name = metadata.get("name")
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 64
        or name != name.lower()
        or name.startswith("-")
        or name.endswith("-")
        or "--" in name
        or not all(character.isalnum() or character == "-" for character in name)
    ):
        raise ValueError("Skill name must be 1-64 lowercase alphanumeric characters with hyphens")
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise ValueError("Skill description must be a nonempty string of at most 1024 characters")
    for key in ("license", "allowed-tools"):
        if key in metadata and not isinstance(metadata[key], str):
            raise ValueError(f"Frontmatter {key} must be a string")
    if "compatibility" in metadata:
        compatibility = metadata["compatibility"]
        if not isinstance(compatibility, str) or not 1 <= len(compatibility) <= 500:
            raise ValueError("Frontmatter compatibility must be a string of 1-500 characters")
    if "metadata" in metadata:
        additional = metadata["metadata"]
        if not isinstance(additional, dict) or not all(
            isinstance(value, str) for value in additional.values()
        ):
            raise ValueError("Frontmatter metadata must map string keys to string values")
    return metadata


def build_skill_manifest(
    snapshot: SkillSnapshot, *, skill_path: str | None = None
) -> dict[str, Any]:
    """Build a complete JSON manifest without rewriting any captured bytes.

    ``skill_path`` is an unescaped server-chosen path ending in the frontmatter
    name. By default an alias becomes a prefix, preserving the declared name
    as the final segment. This does not establish publisher trust.

    Args:
        snapshot: The complete original file capture to describe.
        skill_path: Optional unescaped canonical path ending in the declared name.

    Returns:
        A JSON-compatible skill entry with every author field and file digest.

    Raises:
        ValueError: Frontmatter, file paths, publication limits, or skill_path are invalid.
    """
    _paths([file.path for file in snapshot.files], DEFAULT_SNAPSHOT_MAX_FILES)
    if snapshot.total_bytes > DEFAULT_SNAPSHOT_MAX_BYTES:
        raise ValueError("Skill exceeds the 16 MiB native manifest limit")
    frontmatter = _frontmatter(snapshot.get_file("SKILL.md").data)
    name = frontmatter["name"]
    if skill_path is None:
        skill_path = name if snapshot.skill_id == name else f"{snapshot.skill_id}/{name}"
    components = skill_path.split("/")
    if (
        any(component in {"", ".", ".."} for component in components)
        or "\\" in skill_path
        or "\x00" in skill_path
        or components[-1] != name
    ):
        raise ValueError("skill_path must be a relative path ending in the frontmatter name")
    base_uri = "skill://" + "/".join(quote(component, safe="") for component in components)
    resources = [
        {
            "uri": f"{base_uri}/{quote(file.path, safe='/')}",
            "digest": file.digest,
            "size": file.size,
        }
        for file in snapshot.files
    ]
    return {"uri": f"{base_uri}/SKILL.md", "frontmatter": frontmatter, "resources": resources}
