"""Official Skills extension for MCP SDK 2.2 and later in the 2.x line."""

from __future__ import annotations

import mimetypes
import secrets
from collections.abc import Callable, Collection, Mapping, Sequence
from copy import deepcopy
from time import monotonic
from typing import Any

from mcp import MCPError
from mcp.server import MCPServer
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.mcpserver.resources.types import BinaryResource
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import RequestParams, Resource
from pydantic import StrictStr

from agentskills_core import ProviderUnavailableError, Skill, SkillRegistry, SkillUnavailableError
from agentskills_core.manifests import build_skill_manifest
from agentskills_core.policy import Publication, publish_snapshot
from agentskills_core.refresh import CatalogGeneration, SnapshotCatalog
from agentskills_core.snapshots import DEFAULT_SNAPSHOT_MAX_BYTES, SkillSnapshot, capture_skill
from agentskills_core.telemetry import DisclosureEvent, emit_event
from agentskills_core.trust import TrustPolicy

_PROTOCOLS = frozenset({"2026-07-28"})


def _content(data: bytes) -> str | bytes:
    """Return text only when UTF-8 decoding cannot change a byte."""
    if b"\x00" in data:
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data


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
                elif mime_type == "application/octet-stream" and isinstance(
                    _content(file.data), str
                ):
                    mime_type = "text/plain"
                resource = BinaryResource(uri=uri, data=file.data, mime_type=mime_type)
                resource.name = file.path.rsplit("/", 1)[-1]
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


class _LiveSkillsExtension(Extension):
    identifier = "io.modelcontextprotocol/skills"

    def __init__(
        self,
        catalog: SnapshotCatalog,
        paths: Mapping[str, str],
        page_size: int,
        listed: Collection[str] | None,
        observer: Callable[[DisclosureEvent], None] | None,
        origin: str,
    ) -> None:
        self.catalog = catalog
        self.paths = paths
        self.page_size = page_size
        self.listed = listed
        self.observer = observer
        self.origin = origin
        self._generation: str | None = None
        self._compiled: _SkillsExtension | None = None

    def view(self) -> tuple[CatalogGeneration, _SkillsExtension]:
        state = self.catalog.current
        if self._compiled is None or state.generation != self._generation:
            compiled = _SkillsExtension(
                [entry.snapshot for entry in state.publications],
                self.paths,
                self.page_size,
                self.listed,
            )
            for entry in state.publications:
                manifest = build_skill_manifest(
                    entry.snapshot, skill_path=self.paths.get(entry.snapshot.skill_id)
                )
                metadata = {
                    "io.agentskills/publication": {
                        "origin": entry.source_identity.origin,
                        "revision": entry.revision,
                        "sourceRevision": entry.source_identity.revision,
                        "sourceStatus": entry.source_identity.status,
                        "publisher": entry.source_identity.publisher,
                        "transformed": entry.transformed,
                        "annotations": list(entry.annotations),
                    }
                }
                for resource in manifest["resources"]:
                    compiled._resources[resource["uri"]].meta = metadata
            self._compiled = compiled
            self._generation = state.generation
        return state, self._compiled

    def resources(self) -> Sequence[ResourceBinding]:
        return ()

    def methods(self) -> Sequence[MethodBinding]:
        return (
            MethodBinding("skills/list", _ListParams, self._list, _PROTOCOLS),
            MethodBinding("skills/get", _GetParams, self._get, _PROTOCOLS),
        )

    async def _list(self, context: Any, params: _ListParams) -> dict[str, Any]:
        started = monotonic()
        state, compiled = self.view()
        result = await compiled._list(context, params)
        result["_meta"] = {
            "io.agentskills/catalog": {"generation": state.generation, "stale": state.stale}
        }
        emit_event(
            self.observer,
            "discovery",
            origin=self.origin,
            status="stale" if state.stale else "ok",
            duration_seconds=monotonic() - started,
        )
        return result

    async def _get(self, context: Any, params: _GetParams) -> dict[str, Any]:
        started = monotonic()
        state, compiled = self.view()
        result = await compiled._get(context, params)
        result["_meta"] = {
            "io.agentskills/catalog": {"generation": state.generation, "stale": state.stale}
        }
        emit_event(
            self.observer,
            "lookup",
            origin=self.origin,
            revision=compiled._resources[params.uri].meta["io.agentskills/publication"]["revision"],
            status="stale" if state.stale else "ok",
            duration_seconds=monotonic() - started,
        )
        return result


class NativeSkillsServer(MCPServer):
    """Native server with explicit refresh and audience-scoped readiness.

    Call ``refresh`` from an application-owned control path. Keep providers open
    for its lifetime. Neither refresh nor health is an MCP execution tool.
    """

    def __init__(self, extension: _LiveSkillsExtension, **kwargs: Any) -> None:
        self._skills_extension = extension
        super().__init__(extensions=[extension], **kwargs)

    async def refresh(self) -> dict[str, Any]:
        """Atomically republish fresh source content, applying current policies."""
        await self._skills_extension.catalog.refresh()
        return self.health()

    def health(self) -> dict[str, Any]:
        """Report publication readiness without implying deployment certification."""
        catalog = self._skills_extension.catalog
        if not catalog.ready:
            return {"ready": False}
        state = catalog.current
        return {
            "ready": True,
            "generation": state.generation,
            "stale": state.stale,
            "skillCount": len(state.publications),
        }

    async def list_resources(self) -> list[Resource]:
        """List only the current coherent resource generation."""
        _, compiled = self._skills_extension.view()
        return [
            Resource(
                uri=resource.uri,
                name=resource.name or "",
                description=resource.description,
                mime_type=resource.mime_type,
                _meta=resource.meta,
            )
            for resource in compiled._resources.values()
        ]

    async def read_resource(self, uri: Any, context: Any = None) -> list[ReadResourceContents]:
        """Read captured bytes, never refetching or implicitly activating a skill."""
        started = monotonic()
        extension = self._skills_extension
        state, compiled = extension.view()
        resource = compiled._resources.get(str(uri))
        if resource is None:
            raise MCPError(-32602, "Unknown skill resource")
        metadata = deepcopy(resource.meta)
        metadata["io.agentskills/publication"]["stale"] = state.stale
        emit_event(
            extension.observer,
            "fetch",
            origin=extension.origin,
            revision=metadata["io.agentskills/publication"]["revision"],
            status="stale" if state.stale else "ok",
            byte_count=len(resource.data),
            cache_hit=True,
            duration_seconds=monotonic() - started,
        )
        return [
            ReadResourceContents(
                content=_content(resource.data), mime_type=resource.mime_type, meta=metadata
            )
        ]

    def secure_http_app(
        self, *, allowed_hosts: Sequence[str], allowed_origins: Sequence[str]
    ) -> Any:
        """Build remote HTTP with explicit origin/host policy and MCP authorization.

        Supply ``auth`` and ``token_verifier`` at construction. Terminate TLS
        through the deployment. Use a distinct server/catalog for each audience.
        This helper never forwards incoming tokens to skill providers.
        """
        if (
            not allowed_hosts
            or not allowed_origins
            or any("*" in value for value in (*allowed_hosts, *allowed_origins))
        ):
            raise ValueError("Remote HTTP requires explicit non-wildcard hosts and origins")
        if self.settings.auth is None:
            raise ValueError("Remote HTTP requires deployment-supplied MCP authorization")
        return self.streamable_http_app(
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=list(allowed_hosts),
                allowed_origins=list(allowed_origins),
            )
        )


async def create_mcp_server(
    skills: SkillRegistry | Sequence[Skill],
    *,
    name: str = "AgentSkills",
    instructions: str | None = None,
    skill_paths: Mapping[str, str] | None = None,
    listed_skill_ids: Collection[str] | None = None,
    page_size: int = 100,
    max_skills: int = 128,
    max_total_bytes: int = 64 * 1024 * 1024,
    publication_policy: Callable[[SkillSnapshot], Publication] | None = None,
    origin: str = "unconfigured",
    max_stale_age: float = 0,
    observer: Callable[[DisclosureEvent], None] | None = None,
    auth: AuthSettings | None = None,
    token_verifier: TokenVerifier | None = None,
) -> NativeSkillsServer:
    """Capture immutable sources and serve the official Skills extension.

    Requires MCP SDK 2.2+ and protocol 2026-07-28. No tools, catalog
    injection, execution, or directory-read capability are registered.
    Call ``await server.refresh()`` to publish a new snapshot. Callers supply only skills
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
        publication_policy: Trusted verifier/content policy called before manifests.
            Omission explicitly publishes unsigned content, never verified content.
        origin: Stable non-secret source identity, not a display name.
        max_stale_age: Opt-in maximum age in seconds for verified outage snapshots.
        observer: Optional privacy-preserving disclosure observer.
        auth: Deployment-supplied MCP authorization settings for remote HTTP.
        token_verifier: Deployment-supplied token validator. Never reused upstream.

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

    async def load() -> list[SkillSnapshot]:
        current_handles = (
            skills.list_skills() if isinstance(skills, SkillRegistry) else list(skills)
        )
        if len(current_handles) > max_skills:
            raise ValueError("Skill registry exceeds max_skills")
        snapshots = []
        remaining = max_total_bytes
        previous = (
            {source.skill_id: source for source in catalog.current.sources} if catalog.ready else {}
        )
        changed = (
            bool(previous) and {skill.get_id() for skill in current_handles} != previous.keys()
        )
        for skill in current_handles:
            started = monotonic()
            try:
                snapshot = await capture_skill(
                    skill,
                    max_total_bytes=min(DEFAULT_SNAPSHOT_MAX_BYTES, remaining),
                    previous_snapshot=previous.get(skill.get_id()),
                )
            except ProviderUnavailableError:
                if changed:
                    raise SkillUnavailableError(
                        "Catalog changed before a provider outage"
                    ) from None
                raise
            changed = changed or (bool(previous) and previous.get(skill.get_id()) != snapshot)
            snapshots.append(snapshot)
            remaining -= snapshot.total_bytes
            emit_event(
                observer,
                "fetch",
                origin=origin,
                byte_count=snapshot.total_bytes,
                duration_seconds=monotonic() - started,
            )
        return snapshots

    def publish(snapshot: SkillSnapshot) -> Publication:
        started = monotonic()
        try:
            result = (
                publication_policy(snapshot)
                if publication_policy is not None
                else publish_snapshot(snapshot, trust=TrustPolicy(origin, require_signature=False))
            )
        except Exception:
            emit_event(
                observer,
                "verification",
                origin=origin,
                status="error",
                duration_seconds=monotonic() - started,
            )
            raise
        emit_event(
            observer,
            "verification",
            origin=origin,
            revision=result.revision,
            duration_seconds=monotonic() - started,
        )
        return result

    def validate(publications: Sequence[Publication]) -> None:
        _SkillsExtension([entry.snapshot for entry in publications], paths, page_size, listed)

    catalog = SnapshotCatalog(
        load,
        publish,
        validate=validate,
        max_skills=max_skills,
        max_total_bytes=max_total_bytes,
        max_stale_age=max_stale_age,
        observer=observer,
        origin=origin,
    )
    await catalog.refresh()
    extension = _LiveSkillsExtension(catalog, paths, page_size, listed, observer, origin)
    return NativeSkillsServer(
        extension, name=name, instructions=instructions, auth=auth, token_verifier=token_verifier
    )
