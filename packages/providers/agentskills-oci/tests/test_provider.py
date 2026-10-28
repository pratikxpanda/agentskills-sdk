from __future__ import annotations

import hashlib
from collections.abc import Iterator
from copy import deepcopy

import pytest
import requests
from oras.auth import AuthenticationException

from agentskills_core import (
    AgentSkillsError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillUnavailableError,
)
from agentskills_oci import OCISkillProvider
from agentskills_oci.provider import (
    OCI_IMAGE_MANIFEST,
    OCI_SKILL_ARTIFACT,
    OCI_SKILL_FILE_LAYER,
    OCI_TITLE_ANNOTATION,
)
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


class _Response:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code
        self.closed = False

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]

    def close(self) -> None:
        self.closed = True


class _Session:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeOrasClient:
    def __init__(
        self,
        manifests: dict[str, dict],
        blobs: dict[str, bytes],
        tags: list[str] | None = None,
    ) -> None:
        self.manifests = manifests
        self.blobs = blobs
        self.tags = list(tags or manifests)
        self.session = _Session()
        self.blob_reads: list[str] = []

    def get_container(self, name: str) -> str:
        return name

    def get_tags(self, container: str) -> list[str]:
        assert container
        return self.tags.copy()

    def get_manifest(self, container: str, *, allowed_media_type: list[str]) -> dict:
        assert allowed_media_type == [OCI_IMAGE_MANIFEST]
        _, tag = container.rsplit(":", 1)
        if tag not in self.manifests:
            raise SkillNotFoundError(tag)
        return deepcopy(self.manifests[tag])

    def get_blob(self, container: str, digest: str, *, stream: bool) -> _Response:
        assert container
        assert stream
        self.blob_reads.append(digest)
        return _Response(self.blobs[digest])


def _file_layer(path: str, content: bytes) -> tuple[dict, str, bytes]:
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    return (
        {
            "mediaType": OCI_SKILL_FILE_LAYER,
            "digest": digest,
            "size": len(content),
            "annotations": {OCI_TITLE_ANNOTATION: path},
        },
        digest,
        content,
    )


def _artifact(skill_id: str, files: dict[str, bytes]) -> tuple[dict, dict[str, bytes]]:
    layers = []
    blobs = {}
    for path, content in files.items():
        layer, digest, blob = _file_layer(path, content)
        layers.append(layer)
        blobs[digest] = blob
    return (
        {
            "schemaVersion": 2,
            "mediaType": OCI_IMAGE_MANIFEST,
            "artifactType": OCI_SKILL_ARTIFACT,
            "annotations": {OCI_TITLE_ANNOTATION: skill_id},
            "layers": layers,
        },
        blobs,
    )


def _provider(
    client: _FakeOrasClient,
    *,
    max_file_bytes: int = 10 * 1024 * 1024,
    max_total_bytes: int = 16 * 1024 * 1024,
    max_files: int = 512,
) -> OCISkillProvider:
    return OCISkillProvider(
        "ghcr.io/acme/skills",
        client=client,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        max_files=max_files,
    )


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"HTTP {status}", response=response)


def _raise(error: Exception):
    def fail(*_args, **_kwargs):
        raise error

    return fail


class TestOCISkillProvider:
    def test_given_invalid_repository_or_limits_when_created_then_rejects_configuration(self):
        client = _FakeOrasClient({}, {})
        for repository in ("", "https://ghcr.io/acme/skills", "user:pass@ghcr.io/acme/skills"):
            with pytest.raises(ValueError, match="repository"):
                OCISkillProvider(repository, client=client)
        with pytest.raises(ValueError, match="limits"):
            OCISkillProvider("ghcr.io/acme/skills", client=client, max_files=0)
        with pytest.raises(ValueError, match="Configure TLS"):
            OCISkillProvider("ghcr.io/acme/skills", client=client, insecure=True)

    async def test_given_owned_client_when_context_exits_then_closes_session(self, monkeypatch):
        client = _FakeOrasClient({}, {})
        options = {}

        def create_client(**kwargs):
            options.update(kwargs)
            return client

        monkeypatch.setattr("agentskills_oci.provider.OrasClient", create_client)
        provider = OCISkillProvider("ghcr.io/acme/skills", tls_verify="custom-ca.pem")

        async with provider as entered:
            assert entered is provider

        assert options == {
            "insecure": False,
            "tls_verify": "custom-ca.pem",
            "auth_backend": "token",
        }
        assert client.session.closed

    async def test_given_skill_tag_when_discovered_then_does_not_read_file_layers(self):
        manifest, blobs = _artifact("alpha", {"SKILL.md": b"body"})
        client = _FakeOrasClient({"alpha": manifest}, blobs, ["alpha", "latest", "sha256-deadbeef"])
        provider = _provider(client)

        assert await provider.discover() == ["alpha"]
        assert client.blob_reads == []

    async def test_given_file_layer_when_read_then_verifies_digest_and_bytes(self):
        manifest, blobs = _artifact("alpha", {"SKILL.md": b"body"})
        client = _FakeOrasClient({"alpha": manifest}, blobs)
        provider = _provider(client)

        assert await provider.read_file("alpha", "SKILL.md") == b"body"
        assert len(client.blob_reads) == 1

        assert await provider.list_files("alpha") == ["SKILL.md"]
        assert await provider.list_files("alpha") == ["SKILL.md"]
        assert len(provider._manifest_cache) == 1
        assert len(provider._file_cache) == 1

    async def test_given_manifest_path_traversal_when_listed_then_rejects_artifact(self):
        manifest, blobs = _artifact("alpha", {"SKILL.md": b"body"})
        manifest["layers"].append(_file_layer("../outside", b"bad")[0])
        client = _FakeOrasClient({"alpha": manifest}, blobs)

        with pytest.raises(AgentSkillsError, match="unsafe file path"):
            await _provider(client).list_files("alpha")

    async def test_given_manifest_title_or_artifact_type_mismatch_when_loaded_then_rejects_tag(
        self,
    ):
        manifest, blobs = _artifact("alpha", {"SKILL.md": b"body"})
        manifest["annotations"][OCI_TITLE_ANNOTATION] = "other"
        with pytest.raises(AgentSkillsError, match="title must match"):
            await _provider(_FakeOrasClient({"alpha": manifest}, blobs)).list_files("alpha")

        manifest, blobs = _artifact("alpha", {"SKILL.md": b"body"})
        manifest["artifactType"] = "application/vnd.other"
        with pytest.raises(SkillNotFoundError, match="not an Agent Skills artifact"):
            await _provider(_FakeOrasClient({"alpha": manifest}, blobs)).list_files("alpha")

    async def test_given_invalid_layer_descriptor_when_listed_then_rejects_artifact(self):
        invalid_layers = [
            {
                "mediaType": "text/plain",
                "digest": "sha256:" + "a" * 64,
                "size": 1,
                "annotations": {OCI_TITLE_ANNOTATION: "SKILL.md"},
            },
            {
                "mediaType": OCI_SKILL_FILE_LAYER,
                "digest": "sha512:abcd",
                "size": 1,
                "annotations": {OCI_TITLE_ANNOTATION: "SKILL.md"},
            },
            {
                "mediaType": OCI_SKILL_FILE_LAYER,
                "digest": "sha256:" + "a" * 64,
                "size": -1,
                "annotations": {OCI_TITLE_ANNOTATION: "SKILL.md"},
            },
            {"mediaType": OCI_SKILL_FILE_LAYER, "digest": "sha256:" + "a" * 64, "size": 1},
        ]
        for layer in invalid_layers:
            manifest, blobs = _artifact("alpha", {"SKILL.md": b"body"})
            manifest["layers"] = [layer]
            with pytest.raises(AgentSkillsError):
                await _provider(_FakeOrasClient({"alpha": manifest}, blobs)).list_files("alpha")

    async def test_given_duplicate_or_missing_skill_layer_when_listed_then_rejects_artifact(self):
        manifest, blobs = _artifact("alpha", {"SKILL.md": b"body"})
        manifest["layers"].append(deepcopy(manifest["layers"][0]))
        with pytest.raises(AgentSkillsError, match="duplicate file paths"):
            await _provider(_FakeOrasClient({"alpha": manifest}, blobs)).list_files("alpha")

        manifest, blobs = _artifact("alpha", {"SKILL.md": b"body"})
        manifest["layers"][0]["annotations"][OCI_TITLE_ANNOTATION] = "references/guide.md"
        with pytest.raises(AgentSkillsError, match=r"include SKILL\.md"):
            await _provider(_FakeOrasClient({"alpha": manifest}, blobs)).list_files("alpha")

    async def test_given_manifest_limits_exceeded_when_listed_then_rejects_artifact(self):
        manifest, blobs = _artifact("alpha", {"SKILL.md": b"body", "assets/a.bin": b"x"})
        with pytest.raises(AgentSkillsError, match="layer count"):
            await _provider(_FakeOrasClient({"alpha": manifest}, blobs), max_files=1).list_files(
                "alpha"
            )
        with pytest.raises(AgentSkillsError, match="total file size"):
            await _provider(
                _FakeOrasClient({"alpha": manifest}, blobs), max_total_bytes=1
            ).list_files("alpha")
        with pytest.raises(AgentSkillsError, match="oversized file size"):
            await _provider(
                _FakeOrasClient({"alpha": manifest}, blobs), max_file_bytes=1
            ).list_files("alpha")

    @pytest.mark.parametrize(
        ("status", "expected"),
        [(404, SkillNotFoundError), (401, AgentSkillsError), (503, SkillUnavailableError)],
    )
    async def test_given_manifest_http_status_when_loaded_then_maps_error(
        self, monkeypatch, status, expected
    ):
        client = _FakeOrasClient({}, {})
        monkeypatch.setattr(client, "get_manifest", _raise(_http_error(status)))

        with pytest.raises(expected):
            await _provider(client).list_files("alpha")

    async def test_given_manifest_connection_error_when_loaded_then_maps_unavailable(
        self, monkeypatch
    ):
        client = _FakeOrasClient({}, {})
        monkeypatch.setattr(client, "get_manifest", _raise(requests.ConnectionError("offline")))

        with pytest.raises(SkillUnavailableError):
            await _provider(client).list_files("alpha")

    async def test_given_tag_listing_error_when_discovered_then_maps_error(self, monkeypatch):
        client = _FakeOrasClient({}, {})
        monkeypatch.setattr(client, "get_tags", _raise(requests.ConnectionError("offline")))

        with pytest.raises(SkillUnavailableError):
            await _provider(client).discover()

        monkeypatch.setattr(client, "get_tags", _raise(AuthenticationException("denied")))
        with pytest.raises(AgentSkillsError, match="authentication failed"):
            await _provider(client).discover()

    async def test_given_corrupt_layer_when_read_then_rejects_digest_mismatch(self):
        manifest, blobs = _artifact("alpha", {"SKILL.md": b"body"})
        digest = manifest["layers"][0]["digest"]
        blobs[digest] = b"tampered"
        client = _FakeOrasClient({"alpha": manifest}, blobs)

        with pytest.raises(AgentSkillsError, match="integrity check failed"):
            await _provider(client).read_file("alpha", "SKILL.md")

    async def test_given_invalid_utf8_skill_when_read_then_raises_library_error(self):
        manifest, blobs = _artifact("alpha", {"SKILL.md": b"\xff"})
        client = _FakeOrasClient({"alpha": manifest}, blobs)

        with pytest.raises(AgentSkillsError, match="UTF-8"):
            await _provider(client).get_body("alpha")

    async def test_given_missing_layer_when_read_then_raises_resource_not_found(self):
        manifest, _ = _artifact("alpha", {"SKILL.md": b"body"})
        client = _FakeOrasClient({"alpha": manifest}, {})
        client.get_blob = lambda *_args, **_kwargs: _Response(b"", status_code=404)

        with pytest.raises(AgentSkillsError, match="layer referenced by the manifest is missing"):
            await _provider(client).read_file("alpha", "SKILL.md")

    async def test_given_blob_status_or_connection_error_when_read_then_maps_error(
        self, monkeypatch
    ):
        manifest, blobs = _artifact("alpha", {"SKILL.md": b"body"})
        client = _FakeOrasClient({"alpha": manifest}, blobs)
        monkeypatch.setattr(client, "get_blob", _raise(requests.ConnectionError("offline")))

        with pytest.raises(SkillUnavailableError):
            await _provider(client).read_file("alpha", "SKILL.md")

        for status, error in ((403, AgentSkillsError), (503, SkillUnavailableError)):
            response_client = _FakeOrasClient({"alpha": manifest}, blobs)
            monkeypatch.setattr(
                response_client,
                "get_blob",
                lambda *_args, status=status, **_kwargs: _Response(b"", status_code=status),
            )
            with pytest.raises(error):
                await _provider(response_client).read_file("alpha", "SKILL.md")

    async def test_given_stream_larger_than_layer_size_when_read_then_stops_at_file_limit(self):
        manifest, blobs = _artifact("alpha", {"SKILL.md": b"x"})
        manifest["layers"][0]["size"] = 1
        blobs[manifest["layers"][0]["digest"]] = b"xx"

        with pytest.raises(AgentSkillsError, match="file size limit"):
            await _provider(
                _FakeOrasClient({"alpha": manifest}, blobs), max_file_bytes=1
            ).read_file("alpha", "SKILL.md")

    async def test_given_unknown_skill_or_path_when_read_then_raises_lookup_error(self):
        manifest, blobs = _artifact("alpha", {"SKILL.md": b"body"})
        client = _FakeOrasClient({"alpha": manifest}, blobs)
        provider = _provider(client)

        with pytest.raises(SkillNotFoundError):
            await provider.list_files("missing")
        with pytest.raises(ResourceNotFoundError):
            await provider.read_file("alpha", "references/missing.md")

    async def test_given_external_client_when_closed_then_retains_client_ownership(self):
        client = _FakeOrasClient({}, {})
        provider = _provider(client)

        await provider.aclose()

        assert not client.session.closed


class TestOCISkillProviderConformance(ProviderConformanceSuite):
    @pytest.fixture
    def provider(self) -> OCISkillProvider:
        skill = build_skill(SKILL_ID)
        files = {
            "SKILL.md": render_skill_md(skill).encode("utf-8"),
            f"references/{REFERENCE_NAME}": REFERENCE_BYTES,
            f"scripts/{SCRIPT_NAME}": SCRIPT_BYTES,
            f"assets/{ASSET_NAME}": ASSET_BYTES,
        }
        manifest, blobs = _artifact(SKILL_ID, files)
        return _provider(_FakeOrasClient({SKILL_ID: manifest}, blobs))
