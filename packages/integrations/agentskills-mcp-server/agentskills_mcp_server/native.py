"""Opt-in official Skills extension for the modern MCP SDK."""

from __future__ import annotations

import mimetypes
import secrets
from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from typing import Any

from mcp import MCPError
from mcp.server import MCPServer
from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.resources.types import BinaryResource
from mcp.types import RequestParams
from pydantic import StrictStr

from agentskills_core import Skill, SkillRegistry
from agentskills_core.manifests import build_skill_manifest
from agentskills_core.snapshots import DEFAULT_SNAPSHOT_MAX_BYTES, SkillSnapshot, capture_skill

_PROTOCOLS = frozenset({"2026-07-28"})


class _ListParams(RequestParams):
    cursor: StrictStr | None = None


class _GetParams(RequestParams):
    uri: StrictStr


class _SkillsExtension(Extension):
    identifier = "io.modelcontextprotocol/skills"

    def __init__(
        self,
        snapshots: Sequence[SkillSnapshot],
        skill_paths: Mapping[str, str],
        page_size: int,
        listed_skill_ids: Collection[str] | None,
    ) -> None:
        self._page_size = page_size
        self._skills: dict[str, dict[str, Any]] = {}
        self._resources: dict[str, BinaryResource] = {}
        listed_uris: set[str] = set()
        for snapshot in snapshots:
            manifest = build_skill_manifest(snapshot, skill_path=skill_paths.get(snapshot.skill_id))
            if manifest["uri"] in self._skills:
                raise ValueError(f"Duplicate canonical skill URI: {manifest['uri']}")
            self._skills[manifest["uri"]] = manifest
            if listed_skill_ids is None or snapshot.skill_id in listed_skill_ids:
                listed_uris.add(manifest["uri"])
            for file, entry in zip(snapshot.files, manifest["resources"], strict=True):
                uri = entry["uri"]
                mime_type = mimetypes.guess_type(file.path)[0] or "application/octet-stream"
                if file.path.rsplit("/", 1)[-1] == "SKILL.md":
                    mime_type = "text/markdown"
                resource = BinaryResource(uri=uri, data=file.data, mime_type=mime_type)
                if uri in self._resources:
                    previous = self._resources[uri]
                    if previous.data != file.data:
                        raise ValueError(f"Conflicting captured bytes for resource: {uri}")
                self._resources[uri] = resource
        for uri, manifest in self._skills.items():
            prefix = uri.removesuffix("SKILL.md")
            expected = {entry["uri"] for entry in manifest["resources"]}
            published = {file_uri for file_uri in self._resources if file_uri.startswith(prefix)}
            if published != expected:
                raise ValueError(f"Overlapping publication changes the complete file set: {uri}")
            self._resources[uri].name = manifest["frontmatter"]["name"]
            self._resources[uri].description = manifest["frontmatter"]["description"]
        self._entries = [self._skills[uri] for uri in sorted(listed_uris)]
        self._cursors = {
            offset: secrets.token_urlsafe(24)
            for offset in range(page_size, len(self._entries), page_size)
        }
        self._offsets = {cursor: offset for offset, cursor in self._cursors.items()}

    def resources(self) -> Sequence[ResourceBinding]:
        return tuple(ResourceBinding(resource) for resource in self._resources.values())

    def methods(self) -> Sequence[MethodBinding]:
        return (
            MethodBinding("skills/list", _ListParams, self._list, _PROTOCOLS),
            MethodBinding("skills/get", _GetParams, self._get, _PROTOCOLS),
        )

    async def _list(self, context: Any, params: _ListParams) -> dict[str, Any]:
        offset = 0
        if params.cursor is not None:
            if params.cursor not in self._offsets:
                raise MCPError(-32602, "Invalid skills cursor")
            offset = self._offsets[params.cursor]
        result = {
            "resultType": "complete",
            "skills": deepcopy(self._entries[offset : offset + self._page_size]),
            "ttlMs": 0,
            "cacheScope": "private",
        }
        if cursor := self._cursors.get(offset + self._page_size):
            result["nextCursor"] = cursor
        return result

    async def _get(self, context: Any, params: _GetParams) -> dict[str, Any]:
        if params.uri not in self._skills:
            raise MCPError(-32602, "Unknown skill URI")
        return {
            "resultType": "complete",
            "skill": deepcopy(self._skills[params.uri]),
            "ttlMs": 0,
            "cacheScope": "private",
        }


async def create_native_mcp_server(
    skills: SkillRegistry | Sequence[Skill],
    *,
    name: str = "AgentSkills",
    instructions: str | None = None,
    skill_paths: Mapping[str, str] | None = None,
    listed_skill_ids: Collection[str] | None = None,
    page_size: int = 100,
    max_skills: int = 128,
    max_total_bytes: int = 64 * 1024 * 1024,
) -> MCPServer:
    """Capture immutable sources and serve the official Skills extension.

    Requires MCP SDK 2.2+ and protocol 2026-07-28. No legacy tools, catalog
    injection, execution, or directory-read capability are registered.
    Restart the server to publish a new snapshot. Callers supply only skills
    authorized for the server's audience. Hosts retain approval and trust duties.

    Args:
        skills: An existing registry or raw lossless skill handles.
        name: Server display name, not an origin identity or trust assertion.
        instructions: Explicit server instructions, without automatic catalog injection.
        skill_paths: Unescaped paths keyed by handle ID, ending in each declared name.
        listed_skill_ids: Optional listing subset, never an access-control boundary.
        page_size: Complete skill entries per listing page.
        max_skills: Maximum number of captured handles.
        max_total_bytes: Maximum aggregate retained file bytes across captures.

    Returns:
        A modern MCP server ready for stdio or Streamable HTTP transport.

    Raises:
        ValueError: Publication options, manifests, bounds, or overlapping captures conflict.
        FileAccessNotSupportedError: A provider cannot supply complete original files.
        SkillUnavailableError: A source changes during capture or becomes unavailable.
    """
    if page_size < 1 or max_skills < 1 or max_total_bytes < 0:
        raise ValueError("page_size and max_skills must be positive, max_total_bytes nonnegative")
    handles = skills.list_skills() if isinstance(skills, SkillRegistry) else list(skills)
    if len(handles) > max_skills:
        raise ValueError("Skill registry exceeds max_skills")
    skill_ids = {skill.get_id() for skill in handles}
    if len(skill_ids) != len(handles):
        raise ValueError("Duplicate skill IDs")
    paths = dict(skill_paths or {})
    if paths.keys() - skill_ids:
        raise ValueError("skill_paths contains unknown skill IDs")
    listed = None if listed_skill_ids is None else frozenset(listed_skill_ids)
    if listed is not None and listed - skill_ids:
        raise ValueError("listed_skill_ids contains unknown skill IDs")
    snapshots: list[SkillSnapshot] = []
    remaining = max_total_bytes
    for skill in handles:
        snapshot = await capture_skill(
            skill, max_total_bytes=min(DEFAULT_SNAPSHOT_MAX_BYTES, remaining)
        )
        snapshots.append(snapshot)
        remaining -= snapshot.total_bytes
    extension = _SkillsExtension(snapshots, paths, page_size, listed)
    return MCPServer(name, instructions=instructions, extensions=[extension])
