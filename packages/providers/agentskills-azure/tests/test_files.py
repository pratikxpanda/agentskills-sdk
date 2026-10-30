from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from azure.core.exceptions import AzureError
from azure.core.exceptions import ResourceNotFoundError as AzureResourceNotFoundError

from agentskills_azure.files import AzureFilesSkillProvider
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


class _Download:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def chunks(self) -> AsyncIterator[bytes]:
        yield self.content[:1]
        yield self.content[1:]


class _File:
    def __init__(self, share: _Share, path: str) -> None:
        self.share = share
        self.path = path

    async def get_file_properties(self) -> SimpleNamespace:
        if self.path not in self.share.files:
            raise AzureResourceNotFoundError("missing file")
        return SimpleNamespace(
            size=self.share.sizes.get(self.path, len(self.share.files[self.path])),
            file_attributes=self.share.attributes.get(self.path),
        )

    async def download_file(self, *, decompress: bool) -> _Download:
        assert decompress is False
        self.share.downloads.append(self.path)
        return _Download(self.share.files[self.path])


class _Directory:
    def __init__(self, share: _Share, path: str) -> None:
        self.share = share
        self.path = path

    def get_subdirectory_client(self, name: str) -> _Directory:
        return _Directory(self.share, f"{self.path}/{name}" if self.path else name)

    def get_file_client(self, name: str) -> _File:
        return _File(self.share, f"{self.path}/{name}" if self.path else name)

    async def get_directory_properties(self) -> SimpleNamespace:
        if self.path and not any(path.startswith(self.path + "/") for path in self.share.files):
            raise AzureResourceNotFoundError("missing directory")
        return SimpleNamespace(file_attributes=self.share.attributes.get(self.path))

    async def list_directories_and_files(self, *, include: list[str]) -> AsyncIterator:
        assert include == ["Attributes"]
        prefix = self.path + "/" if self.path else ""
        entries = {}
        for path in self.share.files:
            if path.startswith(prefix):
                name, separator, _ = path[len(prefix) :].partition("/")
                entries[name] = bool(separator)
        for name, is_directory in sorted(entries.items()):
            path = prefix + name
            yield SimpleNamespace(
                name=name,
                is_directory=is_directory,
                file_attributes=self.share.attributes.get(path),
            )


class _Share:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.sizes: dict[str, int] = {}
        self.attributes: dict[str, str] = {}
        self.downloads: list[str] = []
        self.protocols = "SMB"
        self.closed = False
        self.options: dict[str, object] = {}

    async def get_share_properties(self) -> SimpleNamespace:
        return SimpleNamespace(protocols=self.protocols)

    def get_directory_client(self, path: str) -> _Directory:
        return _Directory(self, path)

    async def close(self) -> None:
        self.closed = True


class _Credential:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _provider(
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, bytes],
    **options: object,
) -> AzureFilesSkillProvider:
    share = _Share(files)

    def create_share(*_args: object, **kwargs: object) -> _Share:
        share.options = kwargs
        return share

    monkeypatch.setattr("agentskills_azure.files.ShareClient", create_share)
    monkeypatch.setattr("agentskills_azure.files.DefaultAzureCredential", _Credential)
    return AzureFilesSkillProvider(
        "https://example.file.core.windows.net", "skills", token_intent="backup", **options
    )


class TestAzureFilesSkillProvider:
    async def test_given_real_sdk_when_created_then_accepts_explicit_token_configuration(self):
        provider = AzureFilesSkillProvider(
            "https://example.file.core.windows.net", "skills", token_intent="backup"
        )

        async with provider:
            assert provider._share.url == "https://example.file.core.windows.net/skills"

    def test_given_no_backup_opt_in_when_created_then_rejects_acl_bypass(self) -> None:
        with pytest.raises(ValueError, match="bypasses file ACLs"):
            AzureFilesSkillProvider("https://example.file.core.windows.net", "skills")

    @pytest.mark.parametrize("share_name", ["", ".", "..", "a/b", "a\\b", "a\x00b"])
    def test_given_invalid_share_when_created_then_rejects_name(self, share_name: str) -> None:
        with pytest.raises(ValueError, match="share_name"):
            AzureFilesSkillProvider("https://example.file.core.windows.net", share_name)

    @pytest.mark.parametrize(
        "options", [{"max_file_bytes": -1}, {"max_files": 0}, {"max_depth": -1}]
    )
    def test_given_invalid_limits_when_created_then_rejects_configuration(self, options) -> None:
        with pytest.raises(ValueError, match="limits"):
            AzureFilesSkillProvider("https://example.file.core.windows.net", "skills", **options)

    async def test_given_prefixed_share_when_discover_then_reads_metadata_only(self, monkeypatch):
        provider = _provider(
            monkeypatch,
            {
                "catalog/alpha/SKILL.md": b"---\nname: alpha\ndescription: A skill\n---\n\nBody",
                "catalog/other/readme.txt": b"not a skill",
                "catalog/top-level.txt": b"not a skill",
            },
            prefix="catalog/",
        )

        assert await provider.discover() == ["alpha"]
        assert provider._share.downloads == []
        assert provider._share.options["token_intent"] == "backup"
        assert provider._share.options["allow_trailing_dot"] is True

    async def test_given_nested_files_when_list_then_preserves_paths_without_downloads(
        self, monkeypatch
    ):
        provider = _provider(
            monkeypatch,
            {"alpha/SKILL.md": b"body", "alpha/references/nested/guide.md": b"guide"},
        )

        assert await provider.list_files("alpha") == ["SKILL.md", "references/nested/guide.md"]
        assert provider._share.downloads == []

    @pytest.mark.parametrize("path", ["../escape", "/absolute", "a//b", "a/./b", "a\\b", "\x00"])
    async def test_given_unsafe_path_when_read_then_rejects_before_requests(
        self, monkeypatch, path
    ):
        provider = _provider(monkeypatch, {})

        with pytest.raises(ResourceNotFoundError, match="Invalid skill file path"):
            await provider.read_file("alpha", path)

    async def test_given_missing_skill_when_read_or_list_then_raises_skill_not_found(
        self, monkeypatch
    ):
        provider = _provider(monkeypatch, {"other/readme.txt": b"content"})

        with pytest.raises(SkillNotFoundError):
            await provider.get_body("missing")
        with pytest.raises(SkillNotFoundError):
            await provider.list_files("missing")
        with pytest.raises(SkillNotFoundError):
            await provider.list_files("other")

    async def test_given_missing_resource_when_read_then_raises_resource_not_found(
        self, monkeypatch
    ):
        provider = _provider(monkeypatch, {"alpha/SKILL.md": b"body"})

        with pytest.raises(ResourceNotFoundError):
            await provider.get_asset("alpha", "missing.bin")

    @pytest.mark.parametrize("size", [None, 1])
    async def test_given_oversized_file_when_read_then_enforces_declared_and_streamed_limit(
        self, monkeypatch, size
    ):
        provider = _provider(monkeypatch, {"alpha/SKILL.md": b"12345"}, max_file_bytes=4)
        if size is not None:
            provider._share.sizes["alpha/SKILL.md"] = size

        with pytest.raises(AgentSkillsError, match="exceeds"):
            await provider.read_file("alpha", "SKILL.md")

    async def test_given_nfs_share_when_read_then_rejects_protocol(self, monkeypatch):
        provider = _provider(monkeypatch, {"alpha/SKILL.md": b"body"})
        provider._share.protocols = "NFS"

        with pytest.raises(AgentSkillsError, match="Only SMB"):
            await provider.read_file("alpha", "SKILL.md")

    @pytest.mark.parametrize("path", ["", "alpha", "alpha/assets", "alpha/assets/data.bin"])
    async def test_given_reparse_point_when_read_then_rejects_links(self, monkeypatch, path):
        provider = _provider(
            monkeypatch, {"alpha/SKILL.md": b"body", "alpha/assets/data.bin": b"data"}
        )
        provider._share.attributes[path] = "Archive|ReparsePoint"

        with pytest.raises(ResourceNotFoundError, match="reparse points"):
            await provider.read_file("alpha", "assets/data.bin")

    @pytest.mark.parametrize("options", [{"max_files": 1}, {"max_depth": 0}])
    async def test_given_listing_limit_when_list_then_rejects_excess(self, monkeypatch, options):
        provider = _provider(
            monkeypatch, {"alpha/SKILL.md": b"body", "alpha/assets/data.bin": b"data"}, **options
        )

        with pytest.raises(AgentSkillsError, match="limit"):
            await provider.list_files("alpha")

    async def test_given_invalid_utf8_when_read_body_then_raises_library_error(self, monkeypatch):
        provider = _provider(monkeypatch, {"alpha/SKILL.md": b"\xff"})

        with pytest.raises(AgentSkillsError, match="UTF-8"):
            await provider.get_body("alpha")

    async def test_given_service_error_when_discover_then_raises_library_error(self, monkeypatch):
        provider = _provider(monkeypatch, {})

        async def fail() -> None:
            raise AzureError("denied")

        monkeypatch.setattr(provider._share, "get_share_properties", fail)

        with pytest.raises(AgentSkillsError, match="discovery failed"):
            await provider.discover()

    async def test_given_owned_credential_when_context_exits_then_closes_clients(self, monkeypatch):
        provider = _provider(monkeypatch, {})

        async with provider as entered:
            assert entered is provider

        assert provider._share.closed and provider._credential.closed

    async def test_given_injected_credential_when_closed_then_leaves_it_open(self, monkeypatch):
        credential = _Credential()
        provider = _provider(monkeypatch, {}, credential=credential)

        await provider.aclose()

        assert provider._share.closed and not credential.closed

    async def test_given_share_close_error_when_closed_then_still_closes_owned_credential(
        self, monkeypatch
    ):
        provider = _provider(monkeypatch, {})

        async def fail() -> None:
            raise AzureError("close failed")

        monkeypatch.setattr(provider._share, "close", fail)

        with pytest.raises(AzureError):
            await provider.aclose()
        assert provider._credential.closed


class TestAzureFilesConformance(ProviderConformanceSuite):
    @pytest.fixture
    def provider(self, monkeypatch: pytest.MonkeyPatch) -> AzureFilesSkillProvider:
        skill = build_skill(SKILL_ID)
        return _provider(
            monkeypatch,
            {
                f"{SKILL_ID}/SKILL.md": render_skill_md(skill).encode("utf-8"),
                f"{SKILL_ID}/references/{REFERENCE_NAME}": REFERENCE_BYTES,
                f"{SKILL_ID}/scripts/{SCRIPT_NAME}": SCRIPT_BYTES,
                f"{SKILL_ID}/assets/{ASSET_NAME}": ASSET_BYTES,
            },
        )
