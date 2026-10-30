from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from azure.core.exceptions import AzureError

from agentskills_azure_blob import AzureBlobSkillProvider
from agentskills_core import AgentSkillsError, ResourceNotFoundError, SkillNotFoundError
from agentskills_testing import (
    ASSET_BYTES,
    ASSET_NAME,
    REFERENCE_BYTES,
    REFERENCE_NAME,
    SCRIPT_BYTES,
    SCRIPT_NAME,
    SKILL_ID,
    ProviderConformanceSuite,
    build_skill,
    render_skill_md,
)


class _Downloader:
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def chunks(self) -> AsyncIterator[bytes]:
        yield self._content


class _Blob:
    def __init__(self, content: bytes | None) -> None:
        self._content = content

    async def get_blob_properties(self) -> SimpleNamespace:
        if self._content is None:
            raise _MissingBlobError()
        return SimpleNamespace(size=len(self._content))

    async def download_blob(self) -> _Downloader:
        assert self._content is not None
        return _Downloader(self._content)


class _MissingBlobError(Exception):
    status_code = 404


class _Container:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    async def list_blobs(
        self, *, name_starts_with: str | None = None
    ) -> AsyncIterator[SimpleNamespace]:
        for name in sorted(self._blobs):
            if name_starts_with is None or name.startswith(name_starts_with):
                yield SimpleNamespace(name=name)

    def get_blob_client(self, name: str) -> _Blob:
        return _Blob(self._blobs.get(name))


class _Service:
    def __init__(self, container: _Container) -> None:
        self._container = container
        self.closed = False

    def get_container_client(self, _: str) -> _Container:
        return self._container

    async def close(self) -> None:
        self.closed = True


class _Credential:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _provider(
    monkeypatch: pytest.MonkeyPatch,
    blobs: dict[str, bytes],
    *,
    prefix: str = "",
    max_file_bytes: int = 10 * 1024 * 1024,
    credential: _Credential | None = None,
) -> AzureBlobSkillProvider:
    container = _Container(blobs)
    service = _Service(container)
    default_credential = _Credential()
    monkeypatch.setattr(
        "agentskills_azure_blob.provider.BlobServiceClient",
        lambda *_args, **_kwargs: service,
    )
    monkeypatch.setattr(
        "agentskills_azure_blob.provider.DefaultAzureCredential",
        lambda: default_credential,
    )
    monkeypatch.setattr(
        "agentskills_azure_blob.provider.AzureResourceNotFoundError",
        _MissingBlobError,
    )
    return AzureBlobSkillProvider(
        "https://example.blob.core.windows.net",
        "skills",
        prefix=prefix,
        max_file_bytes=max_file_bytes,
        credential=credential,
    )


class TestAzureBlobSkillProvider:
    def test_given_invalid_container_or_size_when_created_then_rejects_configuration(self):
        with pytest.raises(ValueError, match="container_name"):
            AzureBlobSkillProvider("https://example.blob.core.windows.net", "")
        with pytest.raises(ValueError, match="max_file_bytes"):
            AzureBlobSkillProvider(
                "https://example.blob.core.windows.net", "skills", max_file_bytes=-1
            )

    async def test_given_prefixed_container_when_discover_then_lists_skills(self, monkeypatch):
        provider = _provider(
            monkeypatch,
            {
                "catalog/alpha/SKILL.md": b"---\nname: alpha\ndescription: A skill\n---\n\nBody",
                "catalog/alpha/references/guide.md": b"guide",
                "catalog/invalid/nested/SKILL.md": b"ignored",
                "catalog/not-a-skill/data.txt": b"ignored",
            },
            prefix="catalog/",
        )

        assert await provider.discover() == ["alpha"]
        assert await provider.get_metadata("alpha") == {"name": "alpha", "description": "A skill"}
        assert await provider.get_body("alpha") == "Body"
        assert await provider.list_files("alpha") == ["SKILL.md", "references/guide.md"]
        assert await provider.list_resources("alpha") == {
            "assets": [],
            "references": ["guide.md"],
            "scripts": [],
        }

    async def test_given_binary_file_when_read_then_preserves_bytes(self, monkeypatch):
        provider = _provider(
            monkeypatch,
            {"alpha/SKILL.md": b"text", "alpha/assets/data.bin": b"\x00\xff"},
        )

        assert await provider.get_asset("alpha", "data.bin") == b"\x00\xff"
        assert await provider.read_file("alpha", "assets/data.bin") == b"\x00\xff"

    async def test_given_missing_skill_file_when_read_then_raises_skill_not_found(
        self, monkeypatch
    ):
        provider = _provider(monkeypatch, {})

        with pytest.raises(SkillNotFoundError, match="Skill not found"):
            await provider.get_metadata("missing")

    async def test_given_missing_resource_when_read_then_raises_resource_not_found(
        self, monkeypatch
    ):
        provider = _provider(monkeypatch, {"alpha/SKILL.md": b"text"})

        with pytest.raises(ResourceNotFoundError, match="File not found"):
            await provider.get_asset("alpha", "missing.bin")

    async def test_given_path_traversal_when_read_then_rejects_path(self, monkeypatch):
        provider = _provider(monkeypatch, {})

        with pytest.raises(ResourceNotFoundError, match="Invalid skill file path"):
            await provider.read_file("alpha", "../outside")

    async def test_given_oversized_blob_when_read_then_rejects_file(self, monkeypatch):
        provider = _provider(monkeypatch, {"alpha/SKILL.md": b"12345"}, max_file_bytes=4)

        with pytest.raises(AgentSkillsError, match="exceeds"):
            await provider.read_file("alpha", "SKILL.md")

    async def test_given_stream_larger_than_properties_when_read_then_stops_at_limit(
        self, monkeypatch
    ):
        provider = _provider(monkeypatch, {"alpha/SKILL.md": b"12345"}, max_file_bytes=4)
        monkeypatch.setattr(
            provider._container,
            "get_blob_client",
            lambda _: SimpleNamespace(
                get_blob_properties=_async_properties,
                download_blob=_async_download,
            ),
        )

        with pytest.raises(AgentSkillsError, match="exceeds"):
            await provider.read_file("alpha", "SKILL.md")

    async def test_given_azure_request_error_when_read_then_raises_library_error(self, monkeypatch):
        provider = _provider(monkeypatch, {"alpha/SKILL.md": b"text"})

        async def fail() -> SimpleNamespace:
            raise AzureError("request failed")

        monkeypatch.setattr(
            provider._container,
            "get_blob_client",
            lambda _: SimpleNamespace(get_blob_properties=fail),
        )

        with pytest.raises(AgentSkillsError, match="request failed"):
            await provider.read_file("alpha", "SKILL.md")

    async def test_given_invalid_utf8_skill_when_read_then_raises_library_error(self, monkeypatch):
        provider = _provider(monkeypatch, {"alpha/SKILL.md": b"\xff"})

        with pytest.raises(AgentSkillsError, match="UTF-8"):
            await provider.get_body("alpha")

    async def test_given_owned_credential_when_context_closes_then_closes_clients(
        self, monkeypatch
    ):
        provider = _provider(monkeypatch, {})

        async with provider as entered:
            assert entered is provider

        assert provider._service.closed
        assert provider._credential.closed

    async def test_given_external_credential_when_closed_then_leaves_credential_open(
        self, monkeypatch
    ):
        credential = _Credential()
        provider = _provider(monkeypatch, {}, credential=credential)

        await provider.aclose()

        assert provider._service.closed
        assert not credential.closed


async def _async_properties() -> SimpleNamespace:
    return SimpleNamespace(size=1)


async def _async_download() -> _Downloader:
    return _Downloader(b"12345")


class TestAzureBlobSkillProviderConformance(ProviderConformanceSuite):
    @pytest.fixture
    def provider(self, monkeypatch: pytest.MonkeyPatch) -> AzureBlobSkillProvider:
        skill = build_skill(SKILL_ID)
        blobs = {
            f"{SKILL_ID}/SKILL.md": render_skill_md(skill).encode("utf-8"),
            f"{SKILL_ID}/references/{REFERENCE_NAME}": REFERENCE_BYTES,
            f"{SKILL_ID}/scripts/{SCRIPT_NAME}": SCRIPT_BYTES,
            f"{SKILL_ID}/assets/{ASSET_NAME}": ASSET_BYTES,
        }
        return _provider(monkeypatch, blobs)
