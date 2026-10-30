"""Azure Blob Storage-backed Agent Skills provider."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import AzureError
from azure.core.exceptions import ResourceNotFoundError as AzureResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient

from agentskills_core import (
    RESOURCE_KINDS,
    AgentSkillsError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillProvider,
    split_frontmatter,
)

DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
SKILL_FILE_NAME = "SKILL.md"


class AzureBlobSkillProvider(SkillProvider):
    """Read and discover skills stored as blobs beneath a container prefix.

    A skill is a virtual directory containing ``SKILL.md`` and optional files.
    The provider uses the Azure SDK's asynchronous clients and defaults to
    ``DefaultAzureCredential``. Call :meth:`aclose` when finished, or use the
    provider as an asynchronous context manager.

    Args:
        account_url: Blob service endpoint, such as ``https://account.blob.core.windows.net``.
        container_name: Container holding the skill blobs.
        prefix: Optional path prefix inside the container.
        credential: Optional asynchronous Azure credential. When omitted, the
            provider creates and owns a ``DefaultAzureCredential``.
        max_file_bytes: Maximum size of any file read by the provider.

    Raises:
        ValueError: If the container name, prefix, or size limit is invalid.
    """

    supports_discovery = True
    supports_resource_listing = True
    supports_file_access = True

    def __init__(
        self,
        account_url: str,
        container_name: str,
        *,
        prefix: str = "",
        credential: AsyncTokenCredential | None = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> None:
        if not container_name or "/" in container_name or "\\" in container_name:
            raise ValueError("container_name must be a non-empty container name")
        if max_file_bytes < 0:
            raise ValueError("max_file_bytes must be non-negative")
        self._prefix = self._normalize_prefix(prefix)
        self._max_file_bytes = max_file_bytes
        self._owns_credential = credential is None
        self._credential = credential or DefaultAzureCredential()
        self._service = BlobServiceClient(account_url, credential=self._credential)
        self._container = self._service.get_container_client(container_name)

    async def __aenter__(self) -> AzureBlobSkillProvider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the Blob service client and any credential created by this provider."""
        await self._service.close()
        if self._owns_credential:
            await self._credential.close()

    async def discover(self) -> list[str]:
        """List skill IDs with a top-level ``SKILL.md`` blob."""
        skill_ids: set[str] = set()
        async for blob in self._container.list_blobs(name_starts_with=self._prefix or None):
            relative = blob.name[len(self._prefix) :]
            parts = relative.split("/")
            if len(parts) == 2 and parts[1] == SKILL_FILE_NAME and self._valid_segment(parts[0]):
                skill_ids.add(parts[0])
        return sorted(skill_ids)

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        """Parse and return a skill's YAML frontmatter."""
        raw = await self._read_skill_md(skill_id)
        metadata, _ = split_frontmatter(raw)
        return metadata

    async def get_body(self, skill_id: str) -> str:
        """Return the Markdown body after a skill's YAML frontmatter."""
        raw = await self._read_skill_md(skill_id)
        _, body = split_frontmatter(raw)
        return body

    async def get_script(self, skill_id: str, name: str) -> bytes:
        """Read one script as raw bytes."""
        return await self.read_file(skill_id, f"scripts/{name}")

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        """Read one asset as raw bytes."""
        return await self.read_file(skill_id, f"assets/{name}")

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        """Read one reference as raw bytes."""
        return await self.read_file(skill_id, f"references/{name}")

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        """List direct files in the standard resource directories."""
        paths = await self.list_files(skill_id)
        resources = {kind: [] for kind in RESOURCE_KINDS}
        for path in paths:
            parts = path.split("/")
            if len(parts) == 2 and parts[0] in resources:
                resources[parts[0]].append(parts[1])
        return {kind: sorted(names) for kind, names in resources.items()}

    async def list_files(self, skill_id: str) -> list[str]:
        """List all file paths in a skill without downloading their contents."""
        prefix = self._skill_prefix(skill_id)
        files: list[str] = []
        async for blob in self._container.list_blobs(name_starts_with=prefix):
            relative = blob.name[len(prefix) :]
            if relative and not relative.endswith("/"):
                self._validate_relative_path(relative)
                files.append(relative)
        if SKILL_FILE_NAME not in files:
            raise SkillNotFoundError(f"Skill not found: {skill_id!r}")
        return sorted(files)

    async def read_file(self, skill_id: str, path: str) -> bytes:
        """Read a complete file as original bytes, without newline conversion."""
        relative = self._validate_relative_path(path)
        blob_name = f"{self._skill_prefix(skill_id)}{relative}"
        blob = self._container.get_blob_client(blob_name)
        try:
            properties = await blob.get_blob_properties()
            if properties.size > self._max_file_bytes:
                raise AgentSkillsError(
                    f"File exceeds the {self._max_file_bytes}-byte limit: {relative}"
                )
            chunks: list[bytes] = []
            size = 0
            async for chunk in (await blob.download_blob()).chunks():
                size += len(chunk)
                if size > self._max_file_bytes:
                    raise AgentSkillsError(
                        f"File exceeds the {self._max_file_bytes}-byte limit: {relative}"
                    )
                chunks.append(chunk)
            content = b"".join(chunks)
        except AzureResourceNotFoundError as exc:
            raise ResourceNotFoundError(f"File not found: {skill_id}/{relative}") from exc
        except AzureError as exc:
            raise AgentSkillsError("Azure Blob Storage request failed") from exc
        if len(content) > self._max_file_bytes:
            raise AgentSkillsError(
                f"File exceeds the {self._max_file_bytes}-byte limit: {relative}"
            )
        return content

    async def _read_skill_md(self, skill_id: str) -> str:
        try:
            return (await self.read_file(skill_id, SKILL_FILE_NAME)).decode("utf-8")
        except ResourceNotFoundError as exc:
            raise SkillNotFoundError(f"Skill not found: {skill_id!r}") from exc
        except UnicodeDecodeError as exc:
            raise AgentSkillsError(f"SKILL.md must contain UTF-8 text: {skill_id!r}") from exc

    def _skill_prefix(self, skill_id: str) -> str:
        if not self._valid_segment(skill_id):
            raise SkillNotFoundError(f"Invalid skill ID: {skill_id!r}")
        return f"{self._prefix}{skill_id}/"

    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        if not prefix:
            return ""
        candidate = prefix[:-1] if prefix.endswith("/") else prefix
        path = AzureBlobSkillProvider._validate_relative_path(candidate)
        return f"{path}/"

    @staticmethod
    def _valid_segment(value: str) -> bool:
        return (
            bool(value)
            and value not in {".", ".."}
            and not any(char in value for char in "/\\\x00")
        )

    @staticmethod
    def _validate_relative_path(path: str) -> str:
        candidate = PurePosixPath(path)
        if (
            not path
            or "\\" in path
            or "\x00" in path
            or candidate.is_absolute()
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise ResourceNotFoundError(f"Invalid skill file path: {path!r}")
        return candidate.as_posix()
