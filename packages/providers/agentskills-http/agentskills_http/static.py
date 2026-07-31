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

import asyncio
import json
import random
import re
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from agentskills_core import (
    RESOURCE_KINDS,
    AgentSkillsError,
    ResourceListingNotSupportedError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillProvider,
    SkillUnavailableError,
    get_logger,
    redact_url,
    split_frontmatter,
)

_logger = get_logger(__name__)

# Input validation: identifiers (skill_id, resource name) must be safe
# URL path segments.  Allows alphanumeric, hyphens, dots, underscores.
# Must start with an alphanumeric character.  No path separators or
# traversal sequences (e.g. ``../``).
_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

#: Default maximum HTTP response size in bytes (10 MB).
DEFAULT_MAX_RESPONSE_BYTES: int = 10 * 1024 * 1024

#: Default HTTP request timeout in seconds.
DEFAULT_TIMEOUT_SECONDS: float = 30.0

#: Default number of retries after the initial attempt.
DEFAULT_MAX_RETRIES: int = 2

#: Default base delay for exponential backoff, in seconds.
DEFAULT_RETRY_BACKOFF_SECONDS: float = 0.5

#: Default ceiling on any single backoff sleep, in seconds.
DEFAULT_MAX_RETRY_DELAY_SECONDS: float = 30.0

#: Statuses treated as "gone" rather than "unreachable".
_NOT_FOUND_STATUS_CODES: frozenset[int] = frozenset({404, 410})

#: Non-5xx statuses worth retrying.
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 425, 429})

#: Per-skill manifest filename used for resource listing.
RESOURCE_MANIFEST_NAME: str = "index.json"


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header in either delay-seconds or HTTP-date form."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


@dataclass(frozen=True)
class _CachedSkillMd:
    """A fetched ``SKILL.md`` plus the validators needed to revalidate it."""

    text: str
    etag: str | None
    last_modified: str | None


class HTTPStaticFileSkillProvider(SkillProvider):
    """Skill provider backed by a static HTTP file host.

    The provider expects an HTTP server (S3, Azure Blob, CDN, Nginx,
    GitHub Pages, etc.) that hosts skill files at predictable URL paths.
    Resource names (scripts, assets, references) are discovered by the
    agent from the skill body, or from an optional per-skill
    ``index.json`` manifest -- see *resource_manifest*.

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
        revalidate: If ``True``, re-check cached ``SKILL.md`` content
            on every access using ``If-None-Match`` /
            ``If-Modified-Since``.  Costs one (usually empty) round
            trip per access but picks up republished skills.  Defaults
            to ``False``, which serves cached content until
            :meth:`invalidate` is called.
        resource_manifest: Set ``True`` if the host publishes a per-skill
            ``index.json`` listing resource names.  Enables
            :meth:`list_resources`.  Defaults to ``False``, because a
            plain static host cannot be enumerated and claiming
            otherwise would make missing manifests look like skills with
            no resources.
        timeout: Request timeout in seconds.  Ignored when you supply
            your own *client*.
        max_retries: Retries after the initial attempt, for retryable
            failures only (``5xx``, ``408``, ``425``, ``429``, timeouts,
            connection errors).  ``0`` disables retrying.
        retry_backoff: Base delay in seconds for exponential backoff.
            Actual sleeps are jittered across ``[0, delay]`` so that
            concurrent skill fetches do not retry in lockstep.
        max_retry_delay: Ceiling on any single sleep.  A ``Retry-After``
            longer than this is not waited out -- the error is raised
            immediately with ``retry_after`` attached, because blocking
            a request path for minutes is worse than failing fast and
            letting the caller decide.

    ``SKILL.md`` responses are cached per provider instance, because a
    single skill is otherwise re-fetched up to five times in one agent
    session.  Resource fetches (scripts, assets, references) are not
    cached: they are usually larger and read once.

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
        revalidate: bool = False,
        resource_manifest: bool = False,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        max_retry_delay: float = DEFAULT_MAX_RETRY_DELAY_SECONDS,
    ) -> None:
        if client is not None and (headers is not None or params is not None):
            raise ValueError(
                "Cannot specify both 'client' and 'headers'/'params'. "
                "Configure headers and params on the client directly."
            )
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if retry_backoff <= 0:
            raise ValueError("retry_backoff must be positive")
        if max_retry_delay <= 0:
            raise ValueError("max_retry_delay must be positive")

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
        self._revalidate = revalidate
        self._skill_md_cache: dict[str, _CachedSkillMd] = {}
        self.supports_resource_listing = resource_manifest
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._max_retry_delay = max_retry_delay
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            headers=headers,
            params=params,
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client if it is owned by this provider."""
        if self._owns_client:
            await self._client.aclose()

    def invalidate(self, skill_id: str | None = None) -> None:
        """Drop cached ``SKILL.md`` content.

        Args:
            skill_id: Skill to forget.  Clears the whole cache when
                omitted.  Unknown IDs are ignored.
        """
        if skill_id is None:
            self._skill_md_cache.clear()
        else:
            self._skill_md_cache.pop(skill_id, None)
        _logger.debug("Invalidated SKILL.md cache for %s", skill_id or "all skills")

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
    # Resource listing
    # ------------------------------------------------------------------

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        """List a skill's resources from its ``index.json`` manifest.

        Requires ``resource_manifest=True``.  The manifest is a JSON
        object at ``{base_url}/{skill_id}/index.json`` mapping resource
        kinds to name lists::

            {"references": ["sev.md"], "scripts": ["run.sh"], "assets": []}

        Unknown keys are ignored and missing kinds default to empty.
        Entries that are not valid resource names are dropped, since a
        manifest is host-supplied data and a name is later interpolated
        into a URL.

        Args:
            skill_id: Skill name.

        Returns:
            Mapping of resource kind to sorted resource names.

        Raises:
            ResourceListingNotSupportedError: If the provider was built
                without ``resource_manifest=True``, or the skill has no
                published manifest.
            AgentSkillsError: If the manifest is not a JSON object.
        """
        if not self.supports_resource_listing:
            raise ResourceListingNotSupportedError(
                "This provider was not configured with a resource manifest. "
                "A static HTTP host cannot be enumerated. Pass "
                "resource_manifest=True if the host publishes "
                f"{RESOURCE_MANIFEST_NAME} per skill, otherwise take resource "
                "names from the skill body."
            )

        self._validate_identifier(skill_id, "skill_id")
        url = f"{self._base_url}/{quote(skill_id, safe='')}/{RESOURCE_MANIFEST_NAME}"
        try:
            raw = await self._get_bytes(url)
        except ResourceNotFoundError as exc:
            raise ResourceListingNotSupportedError(
                f"No {RESOURCE_MANIFEST_NAME} manifest published for skill "
                f"{skill_id!r}. Take resource names from the skill body instead."
            ) from exc

        try:
            manifest = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentSkillsError(
                f"Resource manifest for skill {skill_id!r} is not valid JSON"
            ) from exc

        if not isinstance(manifest, dict):
            raise AgentSkillsError(
                f"Resource manifest for skill {skill_id!r} must be a JSON object"
            )

        listing: dict[str, list[str]] = {}
        for kind in RESOURCE_KINDS:
            entries = manifest.get(kind) or []
            if not isinstance(entries, list):
                raise AgentSkillsError(
                    f"Resource manifest for skill {skill_id!r} has a non-list value for {kind!r}"
                )
            listing[kind] = sorted(
                name
                for name in entries
                if isinstance(name, str) and _SAFE_IDENTIFIER_RE.match(name)
            )

        return listing

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _describe(self, url: str) -> str:
        """Describe *url* for an error message or log record without leaking secrets.

        Returns the path relative to *base_url*, so neither the host nor
        any query string can reach a message, a log line, or a
        traceback.  Query strings are where credentials actually live:
        SAS tokens and signed-URL signatures are passed via ``params``.
        """
        return redact_url(url, relative_to=self._base_url)

    async def _stream_bytes(
        self,
        url: str,
        not_found_error: type[Exception],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[bytes | None, httpx.Headers]:
        """Fetch *url*, retrying retryable failures with jittered backoff.

        Args:
            url: The URL to fetch.
            not_found_error: Exception type to raise on 404/410
                (e.g. :class:`SkillNotFoundError` or
                :class:`ResourceNotFoundError`).
            extra_headers: Additional request headers, used to send
                conditional-request validators.

        Returns:
            ``(body, headers)``.  *body* is ``None`` when the server
            answered ``304 Not Modified``.

        Raises:
            not_found_error: On 404 or 410.
            SkillUnavailableError: On 5xx, 408, 425, 429, timeouts and
                connection errors, once retries are exhausted.
            AgentSkillsError: On other HTTP errors, or if the response
                exceeds *max_response_bytes*.
        """
        delay = self._retry_backoff
        for attempt in range(self._max_retries + 1):
            try:
                return await self._attempt_stream(url, not_found_error, extra_headers=extra_headers)
            except SkillUnavailableError as exc:
                if attempt >= self._max_retries:
                    raise
                if exc.retry_after is not None:
                    if exc.retry_after > self._max_retry_delay:
                        raise
                    sleep_for = exc.retry_after
                else:
                    sleep_for = random.uniform(0, min(delay, self._max_retry_delay))
                    delay *= 2
                # No exc_info: httpx exception reprs embed the full URL, query string included.
                _logger.warning(
                    "Retrying %s in %.2fs after attempt %d/%d: %s",
                    self._describe(url),
                    sleep_for,
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )
                await asyncio.sleep(sleep_for)

        raise AssertionError("unreachable: the loop either returns or raises")

    async def _attempt_stream(
        self,
        url: str,
        not_found_error: type[Exception],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[bytes | None, httpx.Headers]:
        """Make a single streaming GET and classify the outcome.

        Uses ``httpx.AsyncClient.stream`` so that overly large
        responses are detected **during** download rather than after
        the entire body has been buffered into memory.
        """
        safe_url = self._describe(url)
        _logger.debug("GET %s", safe_url)
        try:
            async with self._client.stream("GET", url, headers=extra_headers) as resp:
                status = resp.status_code
                if status in _NOT_FOUND_STATUS_CODES:
                    raise not_found_error(f"Skill content not found at {safe_url}")
                if status == 304:
                    return None, resp.headers
                if status in _RETRYABLE_STATUS_CODES or status >= 500:
                    raise SkillUnavailableError(
                        f"HTTP {status} from {safe_url}",
                        retry_after=_parse_retry_after(resp.headers.get("retry-after")),
                    )
                if status in (401, 403):
                    # `from None`: httpx renders the full URL, query string included.
                    raise AgentSkillsError(
                        f"HTTP {status} from {safe_url}. The host rejected the "
                        "request as unauthorised; check the credentials passed via "
                        "'headers' or 'params'."
                    ) from None
                if status >= 400:
                    raise AgentSkillsError(f"HTTP {status} from {safe_url}") from None

                # Check Content-Length header for an early reject when
                # the server advertises the size up-front.
                cl = resp.headers.get("content-length")
                if cl is not None and int(cl) > self._max_response_bytes:
                    raise AgentSkillsError(
                        f"Response exceeds maximum size ({self._max_response_bytes} bytes)"
                    )

                # Stream chunks and enforce the byte limit
                # incrementally to avoid buffering the full body.
                chunks: list[bytes] = []
                received = 0
                async for chunk in resp.aiter_bytes():
                    received += len(chunk)
                    if received > self._max_response_bytes:
                        raise AgentSkillsError(
                            f"Response exceeds maximum size ({self._max_response_bytes} bytes)"
                        )
                    chunks.append(chunk)
                headers = resp.headers

        except (SkillNotFoundError, ResourceNotFoundError, AgentSkillsError):
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
            raise SkillUnavailableError(f"{type(exc).__name__} while fetching {safe_url}") from None
        except httpx.HTTPError as exc:
            raise AgentSkillsError(f"{type(exc).__name__} while fetching {safe_url}") from None

        return b"".join(chunks), headers

    async def _get_bytes(self, url: str) -> bytes:
        """GET a URL and return the response bytes.

        Raises:
            ResourceNotFoundError: On 404.
            AgentSkillsError: On other HTTP or connection errors,
                or if the response exceeds *max_response_bytes*.
        """
        data, _ = await self._stream_bytes(url, ResourceNotFoundError)
        # 304 needs conditional validators, which resource fetches never send.
        return b"" if data is None else data

    async def _get_skill_md(self, skill_id: str) -> str:
        """Fetch a skill's ``SKILL.md``, serving from cache when possible."""
        self._validate_identifier(skill_id, "skill_id")
        url = f"{self._base_url}/{quote(skill_id, safe='')}/SKILL.md"

        cached = self._skill_md_cache.get(skill_id)
        if cached is not None and not self._revalidate:
            _logger.debug("Cache hit for SKILL.md of %r", skill_id)
            return cached.text

        conditional: dict[str, str] = {}
        if cached is not None:
            if cached.etag:
                conditional["If-None-Match"] = cached.etag
            if cached.last_modified:
                conditional["If-Modified-Since"] = cached.last_modified

        data, headers = await self._stream_bytes(
            url, SkillNotFoundError, extra_headers=conditional or None
        )
        if data is None:
            # 304 is only reachable when validators were sent, which requires a cache entry.
            _logger.debug("Revalidated SKILL.md of %r: 304 Not Modified", skill_id)
            return cached.text  # type: ignore[union-attr]

        text = data.decode("utf-8")
        self._skill_md_cache[skill_id] = _CachedSkillMd(
            text=text,
            etag=headers.get("etag"),
            last_modified=headers.get("last-modified"),
        )
        return text

    async def _get_resource(self, skill_id: str, subdir: str, name: str) -> bytes:
        """Fetch a single resource file from a skill subdirectory."""
        self._validate_identifier(skill_id, "skill_id")
        self._validate_identifier(name, "resource name")
        url = f"{self._base_url}/{quote(skill_id, safe='')}/{subdir}/{quote(name, safe='')}"
        return await self._get_bytes(url)
