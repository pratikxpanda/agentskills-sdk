"""HTTP static-file skill provider.

This module implements :class:`HTTPStaticFileSkillProvider`, which fetches
`Agent Skills <https://agentskills.io>`_ from any static HTTP file host.
It expects the same directory-tree layout used by
:class:`~agentskills_fs.LocalFileSystemSkillProvider`, served over HTTP.

Expected URL layout::

    {base_url}/
    ├── incident-response/
    │   ├── SKILL.md                          # YAML frontmatter + markdown body
    │   ├── references/severity-levels.md
    │   ├── scripts/page-oncall.sh
    │   └── assets/flowchart.mermaid
    └── another-skill/
        └── SKILL.md

The provider is a pure content accessor — it does not enumerate or
discover skills.  Registration is handled explicitly by the application
via :meth:`SkillRegistry.register <agentskills_core.SkillRegistry.register>`.
Resource names (scripts, assets, references) are discovered by the agent
from the skill body rather than from a manifest.

All methods are ``async`` and use `httpx <https://www.python-httpx.org/>`_
for non-blocking HTTP requests.
"""

from __future__ import annotations

import logging
import re
import warnings
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from agentskills_core import (
    AgentSkillsError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillProvider,
    split_frontmatter,
)

_logger = logging.getLogger(__name__)

# Input validation: identifiers (skill_id, resource name) must be safe
# URL path segments.  Allows alphanumeric, hyphens, dots, underscores.
# Must start with an alphanumeric character.  No path separators or
# traversal sequences (e.g. ``../``).
_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

#: Default maximum HTTP response size in bytes (10 MB).
DEFAULT_MAX_RESPONSE_BYTES: int = 10 * 1024 * 1024

#: Default HTTP request timeout in seconds.
DEFAULT_TIMEOUT_SECONDS: float = 30.0


class HTTPStaticFileSkillProvider(SkillProvider):
    """Skill provider backed by a static HTTP file host.

    The provider expects an HTTP server (S3, Azure Blob, CDN, Nginx,
    GitHub Pages, etc.) that hosts skill files at predictable URL paths.
    Resource names (scripts, assets, references) are discovered by the
    agent from the skill body rather than from a separate manifest.

    The provider owns an :class:`httpx.AsyncClient` for connection
    pooling.  If you supply your own client the provider will use it
    without closing it.  Otherwise call :meth:`aclose` or use
    ``async with`` when you are finished.

    Args:
        base_url: Root URL where the skill tree is hosted.  A trailing
            slash is stripped automatically.
        client: Optional pre-configured :class:`httpx.AsyncClient`.
            When provided, the caller is responsible for closing it.
            The provider will still enforce *max_response_bytes* but
            will **not** override the client's timeout or redirect
            settings.
        headers: Optional extra headers sent with every request (e.g.
            ``Authorization``).
        params: Optional query parameters appended to every request
            (e.g. SAS tokens for Azure Blob Storage).
        require_tls: If ``True``, reject ``http://`` base URLs with
            a :class:`ValueError`.  Defaults to ``False``, which
            allows HTTP but emits a :class:`UserWarning`.
        max_response_bytes: Maximum allowed response size in bytes.
            Responses exceeding this limit raise
            :class:`~agentskills_core.AgentSkillsError`.  Defaults to
            10 MB.

    Example::

        async with HTTPStaticFileSkillProvider("https://cdn.example.com/skills") as provider:
            registry = SkillRegistry()
            await registry.register("incident-response", provider)

            skill = registry.get_skill("incident-response")
            meta = await skill.get_metadata()
            print(f"{meta['name']}: {meta['description']}")
    """

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        require_tls: bool = False,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if client is not None and (headers is not None or params is not None):
            raise ValueError(
                "Cannot specify both 'client' and 'headers'/'params'. "
                "Configure headers and params on the client directly."
            )

        # TLS enforcement
        parsed = urlparse(base_url)
        if parsed.scheme == "http":
            if require_tls:
                raise ValueError(
                    "require_tls is enabled but base_url uses plain HTTP. "
                    "Use an HTTPS URL or set require_tls=False."
                )
            warnings.warn(
                "base_url uses unencrypted HTTP. "
                "Skill content fetched over HTTP is vulnerable to "
                "man-in-the-middle attacks. Use HTTPS in production.",
                UserWarning,
                stacklevel=2,
            )

        self._base_url = base_url.rstrip("/")
        self._max_response_bytes = max_response_bytes
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            headers=headers,
            params=params,
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client if it is owned by this provider."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> HTTPStaticFileSkillProvider:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        """Raise :class:`ValueError` if *value* is not a safe URL path segment.

        Prevents path-traversal attacks (e.g. ``../``) and other
        injection via ``skill_id`` or resource ``name``.
        """
        if not _SAFE_IDENTIFIER_RE.match(value):
            raise ValueError(
                f"Invalid {label}: {value!r} — must start with an "
                f"alphanumeric character and contain only alphanumeric "
                f"characters, hyphens, dots, and underscores"
            )

    # ------------------------------------------------------------------
    # Metadata & body
    # ------------------------------------------------------------------

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        """Fetch ``SKILL.md`` and return the parsed YAML frontmatter.

        Args:
            skill_id: Skill name to look up.

        Returns:
            Dictionary of frontmatter key-value pairs.

        Raises:
            SkillNotFoundError: If the skill's ``SKILL.md`` cannot be
                fetched.
        """
        raw = await self._get_skill_md(skill_id)
        frontmatter, _ = split_frontmatter(raw)
        return frontmatter

    async def get_body(self, skill_id: str) -> str:
        """Fetch ``SKILL.md`` and return the markdown body.

        Args:
            skill_id: Skill name to look up.

        Returns:
            Markdown instruction text.

        Raises:
            SkillNotFoundError: If the skill's ``SKILL.md`` cannot be
                fetched.
        """
        raw = await self._get_skill_md(skill_id)
        _, body = split_frontmatter(raw)
        return body

    # ------------------------------------------------------------------
    # Scripts
    # ------------------------------------------------------------------

    async def get_script(self, skill_id: str, name: str) -> bytes:
        """Fetch a single script file.

        Args:
            skill_id: Skill name.
            name: Script filename.

        Returns:
            Raw content as bytes.

        Raises:
            ResourceNotFoundError: If the script does not exist.
        """
        return await self._get_resource(skill_id, "scripts", name)

    # ------------------------------------------------------------------
    # Assets
    # ------------------------------------------------------------------

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        """Fetch a single asset file.

        Args:
            skill_id: Skill name.
            name: Asset filename.

        Returns:
            Raw content as bytes.

        Raises:
            ResourceNotFoundError: If the asset does not exist.
        """
        return await self._get_resource(skill_id, "assets", name)

    # ------------------------------------------------------------------
    # References
    # ------------------------------------------------------------------

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        """Fetch a single reference file.

        Args:
            skill_id: Skill name.
            name: Reference filename.

        Returns:
            Raw content as bytes.

        Raises:
            ResourceNotFoundError: If the reference does not exist.
        """
        return await self._get_resource(skill_id, "references", name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_text(self, url: str) -> str:
        """GET a URL and return the response text.

        Raises:
            SkillNotFoundError: On 404.
            AgentSkillsError: On other HTTP or connection errors,
                or if the response exceeds *max_response_bytes*.
        """
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            raise AgentSkillsError("HTTP request failed") from exc
        if resp.status_code == 404:
            raise SkillNotFoundError("Skill content not found")
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AgentSkillsError(f"HTTP {resp.status_code} error") from exc
        if len(resp.content) > self._max_response_bytes:
            raise AgentSkillsError(
                f"Response exceeds maximum size ({self._max_response_bytes} bytes)"
            )
        return resp.text

    async def _get_bytes(self, url: str) -> bytes:
        """GET a URL and return the response bytes.

        Raises:
            ResourceNotFoundError: On 404.
            AgentSkillsError: On other HTTP or connection errors,
                or if the response exceeds *max_response_bytes*.
        """
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            raise AgentSkillsError("HTTP request failed") from exc
        if resp.status_code == 404:
            raise ResourceNotFoundError("Resource not found")
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AgentSkillsError(f"HTTP {resp.status_code} error") from exc
        if len(resp.content) > self._max_response_bytes:
            raise AgentSkillsError(
                f"Response exceeds maximum size ({self._max_response_bytes} bytes)"
            )
        return resp.content

    async def _get_skill_md(self, skill_id: str) -> str:
        """Fetch the full text of a skill's ``SKILL.md``."""
        self._validate_identifier(skill_id, "skill_id")
        url = f"{self._base_url}/{quote(skill_id, safe='')}/SKILL.md"
        return await self._get_text(url)

    async def _get_resource(self, skill_id: str, subdir: str, name: str) -> bytes:
        """Fetch a single resource file from a skill subdirectory."""
        self._validate_identifier(skill_id, "skill_id")
        self._validate_identifier(name, "resource name")
        url = f"{self._base_url}/{quote(skill_id, safe='')}/{subdir}/{quote(name, safe='')}"
        return await self._get_bytes(url)
