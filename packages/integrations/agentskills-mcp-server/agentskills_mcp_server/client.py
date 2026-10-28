"""Framework-neutral client helpers for the official MCP Skills extension."""

from __future__ import annotations

import base64
import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.types import Request
from pydantic import TypeAdapter

_RESPONSE_ADAPTER = TypeAdapter(dict[str, Any])


class McpSkillsClientError(ValueError):
    """Raised when a remote Skills response is malformed or cannot be verified."""


@dataclass(frozen=True, slots=True)
class McpSkillIdentity:
    """An origin-preserving identity for one remote skill."""

    origin: str
    uri: str


@dataclass(frozen=True, slots=True)
class McpSkillReference:
    """A listed remote skill manifest without its eagerly fetched body."""

    identity: McpSkillIdentity
    manifest: dict[str, Any]


class McpSkillsClient:
    """Read native Skills through a caller-owned MCP client session.

    This wrapper is not a :class:`~agentskills_core.SkillProvider`. In
    particular, listing does not fetch bodies or register skills, so the
    host retains selection, approval, activation, and session ownership.
    Each instance is bound to one caller-supplied origin identity and has
    no shared response cache.

    Args:
        session: Initialized session from the official MCP Python client.
        origin: Stable, non-secret identifier for the remote MCP server.

    Raises:
        ValueError: If *origin* is empty.
    """

    def __init__(self, session: ClientSession, *, origin: str) -> None:
        if not origin:
            raise ValueError("origin must not be empty")
        self._session = session
        self.origin = origin

    async def list_skills(self) -> list[McpSkillReference]:
        """List remote skills without reading their content resources.

        Returns:
            Skills in server pagination order, each identified by origin and URI.

        Raises:
            McpSkillsClientError: If a page or cursor is malformed.
        """
        references: list[McpSkillReference] = []
        seen_uris: set[str] = set()
        seen_cursors: set[str] = set()
        cursor: str | None = None
        while True:
            params = {} if cursor is None else {"cursor": cursor}
            page = await self._request("skills/list", params)
            entries = page.get("skills")
            if not isinstance(entries, list):
                raise McpSkillsClientError("skills/list response must include a skills list")
            for entry in entries:
                reference = self._reference(entry)
                if reference.identity.uri in seen_uris:
                    raise McpSkillsClientError("skills/list returned a duplicate skill URI")
                seen_uris.add(reference.identity.uri)
                references.append(reference)
            next_cursor = page.get("nextCursor")
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise McpSkillsClientError("skills/list returned an invalid pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return references

    async def get_skill(self, uri: str) -> McpSkillReference:
        """Look up one canonical skill URI without reading its files.

        Args:
            uri: Canonical ``skill://`` URI from the originating server.

        Returns:
            The complete remote skill manifest and its origin-preserving identity.
        """
        result = await self._request("skills/get", {"uri": uri})
        return self._reference(result.get("skill"))

    async def read_resource(self, skill: McpSkillReference, uri: str) -> bytes:
        """Read one listed file on demand and verify its manifest digest.

        Args:
            skill: Reference returned by :meth:`list_skills` or :meth:`get_skill`.
            uri: Resource URI listed in that skill's manifest.

        Returns:
            Original resource bytes.

        Raises:
            McpSkillsClientError: If the origin, resource, response, size, or digest differs.
        """
        if skill.identity.origin != self.origin:
            raise McpSkillsClientError("skill reference belongs to a different MCP origin")
        resources = skill.manifest.get("resources")
        if not isinstance(resources, list):
            raise McpSkillsClientError("skill manifest must contain a resource list")
        resource = next(
            (entry for entry in resources if isinstance(entry, dict) and entry.get("uri") == uri),
            None,
        )
        if resource is None:
            raise McpSkillsClientError("resource URI is not listed in the skill manifest")

        result = await self._session.read_resource(uri)
        contents = getattr(result, "contents", None)
        if not isinstance(contents, list) or len(contents) != 1:
            raise McpSkillsClientError("resources/read must return one file content block")
        content = contents[0]
        text = getattr(content, "text", None)
        blob = getattr(content, "blob", None)
        if text is not None:
            data = text.encode("utf-8")
        elif isinstance(blob, str):
            try:
                data = base64.b64decode(blob, validate=True)
            except ValueError:
                raise McpSkillsClientError("resources/read returned invalid base64 data") from None
        else:
            raise McpSkillsClientError("resources/read returned no text or blob content")

        digest = resource.get("digest")
        size = resource.get("size")
        if digest != "dynamic":
            actual_digest = "sha256:" + hashlib.sha256(data).hexdigest()
            if digest != actual_digest or size != len(data):
                raise McpSkillsClientError("resource bytes do not match the listed digest and size")
        return data

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self._session.send_request(
            Request[dict[str, Any], str](method=method, params=params), _RESPONSE_ADAPTER
        )
        if not isinstance(response, dict):
            raise McpSkillsClientError(f"{method} response must be an object")
        return response

    def _reference(self, manifest: Any) -> McpSkillReference:
        if not isinstance(manifest, dict):
            raise McpSkillsClientError("Skills response entry must be an object")
        uri = manifest.get("uri")
        resources = manifest.get("resources")
        frontmatter = manifest.get("frontmatter")
        if (
            not isinstance(uri, str)
            or not uri.startswith("skill://")
            or not isinstance(resources, list)
            or not isinstance(frontmatter, dict)
        ):
            raise McpSkillsClientError("Skills response entry is not a complete native manifest")
        return McpSkillReference(McpSkillIdentity(self.origin, uri), deepcopy(manifest))
