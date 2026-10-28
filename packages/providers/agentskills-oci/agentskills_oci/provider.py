"""Read Agent Skills stored as per-file OCI artifact layers."""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any

import requests
from oras.auth import AuthenticationException
from oras.client import OrasClient

from agentskills_core import (
    RESOURCE_KINDS,
    AgentSkillsError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillProvider,
    SkillUnavailableError,
    split_frontmatter,
)

OCI_IMAGE_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_SKILL_ARTIFACT = "application/vnd.agentskills.skill.v1"
OCI_SKILL_FILE_LAYER = "application/vnd.agentskills.file.v1"
OCI_TITLE_ANNOTATION = "org.opencontainers.image.title"
DEFAULT_MAX_FILES = 512
DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 16 * 1024 * 1024
_SKILL_TAG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class OCISkillProvider(SkillProvider):
    """Read skills from OCI artifacts without pulling unrelated file content.

    Each skill is one tag in the configured repository. Its OCI image manifest
    uses ``artifactType`` ``application/vnd.agentskills.skill.v1`` and stores
    each canonical file as a raw layer. The standard
    ``org.opencontainers.image.title`` layer annotation contains the POSIX path
    relative to the skill root. The same annotation on the manifest must match
    the skill tag.

    ORAS authentication and TLS settings remain registry-owned. By default,
    ORAS uses its token auth backend and local Docker-compatible credentials.
    A configured ORAS client can be injected for other registry controls. File
    descriptor digests are verified when blobs are read; publisher signatures
    remain host-verified through ``agentskills-core`` trust policies.

    Args:
        repository: OCI repository, such as ``ghcr.io/acme/agent-skills``.
        client: Optional configured ORAS client. The caller retains ownership.
        insecure: Allow plain HTTP when constructing the default ORAS client.
        tls_verify: TLS verification setting or custom CA bundle path.
        auth_backend: ORAS authentication backend name.
        max_files: Maximum number of file layers in one skill.
        max_file_bytes: Maximum size of an individual file layer.
        max_total_bytes: Maximum aggregate size declared by the manifest.

    Raises:
        ValueError: If the repository or configured limits are invalid.
    """

    supports_discovery = True
    supports_resource_listing = True
    supports_file_access = True

    def __init__(
        self,
        repository: str,
        *,
        client: OrasClient | None = None,
        insecure: bool = False,
        tls_verify: bool | str = True,
        auth_backend: str = "token",
        max_files: int = DEFAULT_MAX_FILES,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    ) -> None:
        if (
            not repository
            or "://" in repository
            or "@" in repository
            or any(character in repository for character in "?# \t\r\n\x00")
        ):
            raise ValueError("repository must be a registry/repository without URL credentials")
        if max_files < 1 or max_file_bytes < 0 or max_total_bytes < 0:
            raise ValueError("OCI skill limits must be non-negative and max_files must be positive")
        if client is not None and (insecure or tls_verify is not True or auth_backend != "token"):
            raise ValueError("Configure TLS and authentication on the supplied ORAS client")
        self.repository = repository
        self._owns_client = client is None
        self._client = client or OrasClient(
            insecure=insecure,
            tls_verify=tls_verify,
            auth_backend=auth_backend,
        )
        self._max_files = max_files
        self._max_file_bytes = max_file_bytes
        self._max_total_bytes = max_total_bytes
        self._manifest_cache: dict[str, dict[str, Any]] = {}
        self._file_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    async def __aenter__(self) -> OCISkillProvider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the ORAS HTTP session when this provider created it."""
        if self._owns_client:
            await asyncio.to_thread(self._client.session.close)

    async def discover(self) -> list[str]:
        """Return skill IDs for tags that identify supported skill artifacts."""
        return await asyncio.to_thread(self._discover_sync)

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        """Parse and return the skill's YAML frontmatter."""
        metadata, _ = split_frontmatter(await self._read_skill_markdown(skill_id))
        return metadata

    async def get_body(self, skill_id: str) -> str:
        """Return the Markdown body after the skill's frontmatter."""
        _, body = split_frontmatter(await self._read_skill_markdown(skill_id))
        return body

    async def get_script(self, skill_id: str, name: str) -> bytes:
        """Read one script layer as original bytes."""
        return await self.read_file(skill_id, f"scripts/{name}")

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        """Read one asset layer as original bytes."""
        return await self.read_file(skill_id, f"assets/{name}")

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        """Read one reference layer as original bytes."""
        return await self.read_file(skill_id, f"references/{name}")

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        """List direct resources in the standard skill directories."""
        files = await self.list_files(skill_id)
        resources = {kind: [] for kind in RESOURCE_KINDS}
        for path in files:
            parts = path.split("/")
            if len(parts) == 2 and parts[0] in resources:
                resources[parts[0]].append(parts[1])
        return {kind: sorted(names) for kind, names in resources.items()}

    async def list_files(self, skill_id: str) -> list[str]:
        """List canonical file paths from the skill manifest without fetching layers."""
        descriptors = await asyncio.to_thread(self._file_descriptors_sync, skill_id)
        return sorted(descriptors)

    async def read_file(self, skill_id: str, path: str) -> bytes:
        """Fetch one file layer and verify its declared size and SHA-256 digest."""
        relative = self._validate_path(path)
        descriptors = await asyncio.to_thread(self._file_descriptors_sync, skill_id)
        descriptor = descriptors.get(relative)
        if descriptor is None:
            raise ResourceNotFoundError(f"Skill '{skill_id}' has no file '{relative}'")
        return await asyncio.to_thread(self._read_blob_sync, skill_id, relative, descriptor)

    async def _read_skill_markdown(self, skill_id: str) -> str:
        raw = await self.read_file(skill_id, "SKILL.md")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AgentSkillsError("OCI SKILL.md must contain UTF-8 text") from exc

    def _discover_sync(self) -> list[str]:
        with self._lock:
            container = self._client.get_container(self.repository)
            try:
                tags = self._client.get_tags(container)
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in {408, 429} or (status is not None and status >= 500):
                    raise self._unavailable_error(exc) from exc
                raise AgentSkillsError("OCI tag listing request failed") from exc
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                raise self._unavailable_error(exc) from exc
            except requests.exceptions.RequestException as exc:
                raise AgentSkillsError("OCI tag listing request failed") from exc
            except AuthenticationException as exc:
                raise AgentSkillsError("OCI registry authentication failed") from exc

            skills = []
            for tag in tags:
                if not _SKILL_TAG.fullmatch(tag):
                    continue
                try:
                    manifest = self._manifest_sync(tag)
                except SkillNotFoundError:
                    continue
                if manifest.get("artifactType") == OCI_SKILL_ARTIFACT:
                    self._file_descriptors_from_manifest(tag, manifest)
                    skills.append(tag)
            return sorted(set(skills))

    def _manifest_sync(self, skill_id: str) -> dict[str, Any]:
        if not _SKILL_TAG.fullmatch(skill_id):
            raise SkillNotFoundError(f"Invalid OCI skill tag: {skill_id!r}")
        with self._lock:
            cached = self._manifest_cache.get(skill_id)
            if cached is not None:
                return deepcopy(cached)
            container = self._client.get_container(f"{self.repository}:{skill_id}")
            try:
                manifest = self._client.get_manifest(
                    container, allowed_media_type=[OCI_IMAGE_MANIFEST]
                )
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 404:
                    raise SkillNotFoundError(f"OCI skill not found: {skill_id!r}") from exc
                if status in {408, 429} or (status is not None and status >= 500):
                    raise self._unavailable_error(exc) from exc
                raise AgentSkillsError("OCI manifest request failed") from exc
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                raise self._unavailable_error(exc) from exc
            except AuthenticationException as exc:
                raise AgentSkillsError("OCI registry authentication failed") from exc

            if (
                manifest.get("schemaVersion") != 2
                or manifest.get("mediaType") != OCI_IMAGE_MANIFEST
                or manifest.get("artifactType") != OCI_SKILL_ARTIFACT
            ):
                raise SkillNotFoundError(f"OCI tag is not an Agent Skills artifact: {skill_id!r}")
            annotations = manifest.get("annotations")
            if (
                not isinstance(annotations, dict)
                or annotations.get(OCI_TITLE_ANNOTATION) != skill_id
            ):
                raise AgentSkillsError("OCI skill manifest title must match its tag")
            self._manifest_cache[skill_id] = deepcopy(manifest)
            return deepcopy(manifest)

    def _file_descriptors_sync(self, skill_id: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            cached = self._file_cache.get(skill_id)
            if cached is not None:
                return deepcopy(cached)
            manifest = self._manifest_sync(skill_id)
            descriptors = self._file_descriptors_from_manifest(skill_id, manifest)
            self._file_cache[skill_id] = descriptors
            return deepcopy(descriptors)

    def _file_descriptors_from_manifest(
        self, skill_id: str, manifest: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        layers = manifest.get("layers")
        if not isinstance(layers, list) or not 1 <= len(layers) <= self._max_files:
            raise AgentSkillsError("OCI skill manifest has an invalid layer count")
        descriptors: dict[str, dict[str, Any]] = {}
        total_size = 0
        for layer in layers:
            if not isinstance(layer, dict) or layer.get("mediaType") != OCI_SKILL_FILE_LAYER:
                raise AgentSkillsError("OCI skill layer has an unsupported media type")
            annotations = layer.get("annotations")
            path = annotations.get(OCI_TITLE_ANNOTATION) if isinstance(annotations, dict) else None
            if not isinstance(path, str):
                raise AgentSkillsError("OCI skill layer is missing its file path annotation")
            try:
                relative = self._validate_path(path)
            except ResourceNotFoundError as exc:
                raise AgentSkillsError("OCI skill manifest contains an unsafe file path") from exc
            digest = layer.get("digest")
            size = layer.get("size")
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                raise AgentSkillsError("OCI skill layer has an unsupported digest")
            if type(size) is not int or size < 0 or size > self._max_file_bytes:
                raise AgentSkillsError("OCI skill layer has an invalid or oversized file size")
            if relative in descriptors:
                raise AgentSkillsError("OCI skill manifest contains duplicate file paths")
            total_size += size
            if total_size > self._max_total_bytes:
                raise AgentSkillsError("OCI skill manifest exceeds the total file size limit")
            descriptors[relative] = deepcopy(layer)
        if "SKILL.md" not in descriptors:
            raise AgentSkillsError("OCI skill manifest must include SKILL.md")
        return descriptors

    def _read_blob_sync(self, skill_id: str, path: str, descriptor: dict[str, Any]) -> bytes:
        with self._lock:
            container = self._client.get_container(f"{self.repository}:{skill_id}")
            response: requests.Response | None = None
            try:
                response = self._client.get_blob(container, descriptor["digest"], stream=True)
                status = response.status_code
                if status == 404:
                    raise AgentSkillsError("OCI skill layer referenced by the manifest is missing")
                if status in {408, 429} or status >= 500:
                    raise SkillUnavailableError("OCI registry could not return a skill layer")
                if status != 200:
                    raise AgentSkillsError("OCI layer request failed")
                chunks: list[bytes] = []
                digest = hashlib.sha256()
                size = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self._max_file_bytes:
                        raise AgentSkillsError("OCI skill layer exceeds the file size limit")
                    digest.update(chunk)
                    chunks.append(chunk)
                actual_digest = "sha256:" + digest.hexdigest()
                if size != descriptor["size"] or actual_digest != descriptor["digest"]:
                    raise AgentSkillsError(f"OCI skill layer integrity check failed: {path}")
                return b"".join(chunks)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                raise self._unavailable_error(exc) from exc
            except requests.exceptions.RequestException as exc:
                raise AgentSkillsError("OCI layer request failed") from exc
            except AuthenticationException as exc:
                raise AgentSkillsError("OCI registry authentication failed") from exc
            finally:
                if response is not None:
                    response.close()

    @staticmethod
    def _validate_path(path: str) -> str:
        candidate = PurePosixPath(path)
        if (
            not path
            or "\\" in path
            or "\x00" in path
            or candidate.is_absolute()
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise ResourceNotFoundError(f"Unsafe OCI skill file path: {path!r}")
        return candidate.as_posix()

    @staticmethod
    def _unavailable_error(exc: Exception) -> SkillUnavailableError:
        return SkillUnavailableError(f"OCI registry request failed ({type(exc).__name__})")
