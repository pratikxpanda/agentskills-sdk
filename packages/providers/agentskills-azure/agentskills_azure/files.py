"""Azure Files-backed Agent Skills provider."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import AzureError
from azure.core.exceptions import ResourceNotFoundError as AzureResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential

from agentskills_core import (
    RESOURCE_KINDS,
    AgentSkillsError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillProvider,
    split_frontmatter,
)

try:
    from azure.storage.fileshare.aio import ShareClient, ShareDirectoryClient
except ModuleNotFoundError as exc:
    raise ImportError("Install 'agentskills-azure[files]' to use AzureFilesSkillProvider.") from exc


class AzureFilesSkillProvider(SkillProvider):
    """Read skills from directories in an Azure Files SMB share.

    Uses the async FileREST SDK, not a mounted filesystem. Token authentication
    requires an explicit ``token_intent="backup"`` opt-in because it bypasses
    file ACLs subject to Azure RBAC. NFS shares and reparse points are rejected.

    Args:
        account_url: File service endpoint, such as ``https://account.file.core.windows.net``.
        share_name: SMB share containing the skill directories.
        prefix: Optional directory beneath which skills are stored.
        credential: Caller-owned async credential. Defaults to an owned
            ``DefaultAzureCredential``.
        token_intent: Must be ``"backup"`` to acknowledge FileREST token semantics.
        max_file_bytes: Maximum bytes returned by a file read.
        max_files: Maximum files listed in one skill.
        max_depth: Maximum nested directory depth inside one skill.

    Raises:
        ValueError: If the share, limits, or token intent are invalid.
        ResourceNotFoundError: If the prefix contains an unsafe path.
    """

    supports_discovery = True
    supports_resource_listing = True
    supports_file_access = True

    def __init__(
        self,
        account_url: str,
        share_name: str,
        *,
        prefix: str = "",
        credential: AsyncTokenCredential | None = None,
        token_intent: Literal["backup"] | None = None,
        max_file_bytes: int = 10 * 1024 * 1024,
        max_files: int = 10_000,
        max_depth: int = 64,
    ) -> None:
        if not self._valid_segment(share_name):
            raise ValueError("share_name must be a non-empty share name")
        if max_file_bytes < 0 or max_files < 1 or max_depth < 0:
            raise ValueError(
                "File size and depth limits must be non-negative and max_files positive"
            )
        if token_intent != "backup":
            raise ValueError(
                "Azure Files token credentials require token_intent='backup'; "
                "this bypasses file ACLs and requires an authorized Azure RBAC role"
            )
        self._prefix = self._validate_path(prefix.removesuffix("/")) if prefix else ""
        self._max_file_bytes = max_file_bytes
        self._max_files = max_files
        self._max_depth = max_depth
        self._owns_credential = credential is None
        self._credential = credential if credential is not None else DefaultAzureCredential()
        self._share = ShareClient(
            account_url,
            share_name,
            credential=self._credential,
            token_intent=token_intent,
            allow_trailing_dot=True,
        )

    async def __aenter__(self) -> AzureFilesSkillProvider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the share client and any provider-owned credential."""
        try:
            await self._share.close()
        finally:
            if self._owns_credential:
                await self._credential.close()

    async def discover(self) -> list[str]:
        """Discover immediate skill directories using metadata only."""
        skill_ids: list[str] = []
        try:
            root = await self._directory(self._prefix)
            async for entry in root.list_directories_and_files(include=["Attributes"]):
                if not entry.is_directory or not self._valid_segment(entry.name):
                    continue
                self._reject_link(entry)
                directory = root.get_subdirectory_client(entry.name)
                self._reject_link(await directory.get_directory_properties())
                try:
                    properties = await directory.get_file_client("SKILL.md").get_file_properties()
                except AzureResourceNotFoundError:
                    continue
                self._reject_link(properties)
                skill_ids.append(entry.name)
        except AzureError as exc:
            raise AgentSkillsError("Azure Files discovery failed") from exc
        return sorted(skill_ids)

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        """Return the skill's YAML frontmatter."""
        metadata, _ = split_frontmatter(await self._read_skill_md(skill_id))
        return metadata

    async def get_body(self, skill_id: str) -> str:
        """Return the Markdown body after the frontmatter."""
        _, body = split_frontmatter(await self._read_skill_md(skill_id))
        return body

    async def get_script(self, skill_id: str, name: str) -> bytes:
        """Read one script without executing it."""
        return await self.read_file(skill_id, f"scripts/{name}")

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        """Read one asset as original bytes."""
        return await self.read_file(skill_id, f"assets/{name}")

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        """Read one reference as original bytes."""
        return await self.read_file(skill_id, f"references/{name}")

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        """List direct files in the standard resource directories."""
        resources = {kind: [] for kind in RESOURCE_KINDS}
        for path in await self.list_files(skill_id):
            parts = path.split("/")
            if len(parts) == 2 and parts[0] in resources:
                resources[parts[0]].append(parts[1])
        return {kind: sorted(names) for kind, names in resources.items()}

    async def list_files(self, skill_id: str) -> list[str]:
        """List canonical files recursively without downloading their contents."""
        root_path = self._skill_path(skill_id)
        try:
            root = await self._directory(root_path)
        except AzureResourceNotFoundError as exc:
            raise SkillNotFoundError(f"Skill not found: {skill_id!r}") from exc
        except AzureError as exc:
            raise AgentSkillsError("Azure Files listing failed") from exc
        files: list[str] = []
        pending = [(root, "", 0)]
        directories = 0
        try:
            while pending:
                directory, relative, depth = pending.pop()
                async for entry in directory.list_directories_and_files(include=["Attributes"]):
                    if not self._valid_segment(entry.name):
                        raise ResourceNotFoundError("Invalid Azure Files directory entry")
                    self._reject_link(entry)
                    path = f"{relative}/{entry.name}" if relative else entry.name
                    if entry.is_directory:
                        directories += 1
                        if depth >= self._max_depth or directories > self._max_files:
                            raise AgentSkillsError("Azure Files directory traversal limit exceeded")
                        child = directory.get_subdirectory_client(entry.name)
                        self._reject_link(await child.get_directory_properties())
                        pending.append((child, path, depth + 1))
                    else:
                        files.append(path)
                        if len(files) > self._max_files:
                            raise AgentSkillsError("Azure Files file count limit exceeded")
        except AzureResourceNotFoundError as exc:
            raise ResourceNotFoundError("Azure Files directory disappeared during listing") from exc
        except AzureError as exc:
            raise AgentSkillsError("Azure Files listing failed") from exc
        if "SKILL.md" not in files:
            raise SkillNotFoundError(f"Skill not found: {skill_id!r}")
        return sorted(files)

    async def read_file(self, skill_id: str, path: str) -> bytes:
        """Read original bytes with preflight and streamed size enforcement."""
        relative = self._validate_path(path)
        full_path = f"{self._skill_path(skill_id)}/{relative}"
        parent, name = full_path.rsplit("/", 1)
        try:
            directory = await self._directory(parent)
            file = directory.get_file_client(name)
            properties = await file.get_file_properties()
            self._reject_link(properties)
            if properties.size > self._max_file_bytes:
                raise AgentSkillsError(
                    f"File exceeds the {self._max_file_bytes}-byte limit: {path}"
                )
            chunks: list[bytes] = []
            size = 0
            async for chunk in (await file.download_file(decompress=False)).chunks():
                size += len(chunk)
                if size > self._max_file_bytes:
                    raise AgentSkillsError(
                        f"File exceeds the {self._max_file_bytes}-byte limit: {path}"
                    )
                chunks.append(chunk)
            return b"".join(chunks)
        except AzureResourceNotFoundError as exc:
            raise ResourceNotFoundError(f"File not found: {skill_id}/{relative}") from exc
        except AzureError as exc:
            raise AgentSkillsError("Azure Files read failed") from exc

    async def _directory(self, path: str) -> ShareDirectoryClient:
        properties = await self._share.get_share_properties()
        if properties.protocols != "SMB":
            raise AgentSkillsError("Only SMB Azure Files shares are supported")
        directory = self._share.get_directory_client("")
        self._reject_link(await directory.get_directory_properties())
        for segment in path.split("/") if path else []:
            directory = directory.get_subdirectory_client(segment)
            self._reject_link(await directory.get_directory_properties())
        return directory

    async def _read_skill_md(self, skill_id: str) -> str:
        try:
            return (await self.read_file(skill_id, "SKILL.md")).decode("utf-8")
        except ResourceNotFoundError as exc:
            raise SkillNotFoundError(f"Skill not found: {skill_id!r}") from exc
        except UnicodeDecodeError as exc:
            raise AgentSkillsError(f"SKILL.md must contain UTF-8 text: {skill_id!r}") from exc

    def _skill_path(self, skill_id: str) -> str:
        if not self._valid_segment(skill_id):
            raise SkillNotFoundError(f"Invalid skill ID: {skill_id!r}")
        return f"{self._prefix}/{skill_id}" if self._prefix else skill_id

    @staticmethod
    def _reject_link(properties: Any) -> None:
        if "reparsepoint" in (properties.file_attributes or "").lower().split("|"):
            raise ResourceNotFoundError("Azure Files reparse points are not supported")

    @staticmethod
    def _valid_segment(value: str) -> bool:
        return (
            bool(value)
            and value not in {".", ".."}
            and not any(char in value for char in "/\\\x00")
        )

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
            raise ResourceNotFoundError(f"Invalid skill file path: {path!r}")
        return candidate.as_posix()
