"""Tests for the origin-preserving MCP Skills client helper."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import Client

from agentskills_core import Skill
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_mcp_extension import (
    McpSkillIdentity,
    McpSkillReference,
    McpSkillsClient,
    McpSkillsClientError,
    McpSkillsCollection,
    create_mcp_server,
)


class _FakeSession:
    def __init__(self, responses: list[object], contents: list[object] | None = None) -> None:
        self.responses = iter(responses)
        self.contents = contents or []

    async def send_request(self, request: object, result_adapter: object) -> object:
        return next(self.responses)

    async def read_resource(self, uri: str) -> object:
        return SimpleNamespace(contents=self.contents)


def _manifest(uri: str = "skill://alpha/SKILL.md") -> dict[str, object]:
    return {
        "uri": uri,
        "frontmatter": {"name": "alpha", "description": "A skill."},
        "resources": [],
    }


def _write_skill(root: Path, skill_id: str, body: str = "# Body") -> Skill:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(
        f"---\nname: {skill_id}\ndescription: A remote skill.\n---\n\n{body}\n".encode()
    )
    assets = skill_dir / "assets"
    assets.mkdir()
    (assets / "image.bin").write_bytes(b"\x00\xff\x80")
    return Skill(skill_id, LocalFileSystemSkillProvider(root))


class TestMcpSkillsClient:
    async def test_given_same_uri_from_two_origins_then_composes_by_identity(
        self, tmp_path: Path
    ) -> None:
        source_a = tmp_path / "source-a"
        source_b = tmp_path / "source-b"
        source_a.mkdir()
        source_b.mkdir()
        server_a = await create_mcp_server(
            [_write_skill(source_a, "alpha", "# From A")], origin="publisher-a"
        )
        server_b = await create_mcp_server(
            [_write_skill(source_b, "alpha", "# From B")], origin="publisher-b"
        )

        async with Client(server_a) as session_a, Client(server_b) as session_b:
            collection = McpSkillsCollection(
                [
                    McpSkillsClient(session_a.session, origin="publisher-a"),
                    McpSkillsClient(session_b.session, origin="publisher-b"),
                ]
            )
            references = await collection.list_skills()
            assert [reference.identity.origin for reference in references] == [
                "publisher-a",
                "publisher-b",
            ]
            assert references[0].identity.uri == references[1].identity.uri

            first = await collection.get_skill(references[0].identity)
            second = await collection.get_skill(references[1].identity)

            assert b"# From A" in await collection.read_resource(first, first.identity.uri)
            assert b"# From B" in await collection.read_resource(second, second.identity.uri)

    def test_given_duplicate_origin_clients_when_composed_then_rejects_ambiguity(self) -> None:
        session = _FakeSession([])

        with pytest.raises(ValueError, match="origins must be unique"):
            McpSkillsCollection(
                [
                    McpSkillsClient(session, origin="same"),
                    McpSkillsClient(session, origin="same"),
                ]
            )

    async def test_given_unknown_origin_identity_when_composed_lookup_then_rejects_origin(self):
        collection = McpSkillsCollection([])
        reference = McpSkillReference(
            McpSkillIdentity("missing-origin", "skill://alpha/SKILL.md"),
            _manifest(),
        )

        with pytest.raises(McpSkillsClientError, match="unknown MCP origin"):
            await collection.get_skill(reference.identity)
        with pytest.raises(McpSkillsClientError, match="unknown MCP origin"):
            await collection.read_resource(reference, reference.identity.uri)

    def test_given_empty_origin_when_initialized_then_rejects_origin(self) -> None:
        with pytest.raises(ValueError, match="origin must not be empty"):
            McpSkillsClient(_FakeSession([]), origin="")

    async def test_given_repeated_cursor_when_listing_then_rejects_pagination_loop(self) -> None:
        session = _FakeSession(
            [
                {"skills": [], "nextCursor": "repeat"},
                {"skills": [], "nextCursor": "repeat"},
            ]
        )

        with pytest.raises(McpSkillsClientError, match="invalid pagination cursor"):
            await McpSkillsClient(session, origin="server").list_skills()

    @pytest.mark.parametrize("response", [[], {"skills": "bad"}])
    async def test_given_malformed_list_response_then_raises_client_error(
        self, response: object
    ) -> None:
        with pytest.raises(McpSkillsClientError, match="skills/list response"):
            await McpSkillsClient(_FakeSession([response]), origin="server").list_skills()

    async def test_given_duplicate_uri_across_pages_when_listed_then_rejects_duplicate(
        self,
    ) -> None:
        entry = _manifest()
        session = _FakeSession(
            [
                {"skills": [entry], "nextCursor": "next"},
                {"skills": [entry]},
            ]
        )

        with pytest.raises(McpSkillsClientError, match="duplicate skill URI"):
            await McpSkillsClient(session, origin="server").list_skills()

    async def test_given_dynamic_resource_when_read_then_returns_bytes_without_digest_check(
        self,
    ) -> None:
        uri = "skill://alpha/assets/live.bin"
        manifest = _manifest()
        manifest["resources"] = [{"uri": uri, "digest": "dynamic", "size": None}]
        reference = McpSkillReference(McpSkillIdentity("server", manifest["uri"]), manifest)
        session = _FakeSession([], [SimpleNamespace(blob="AP8=")])

        assert await McpSkillsClient(session, origin="server").read_resource(reference, uri) == (
            b"\x00\xff"
        )

    async def test_given_invalid_resource_response_when_read_then_rejects_content(self) -> None:
        uri = "skill://alpha/assets/image.bin"
        manifest = _manifest()
        manifest["resources"] = [{"uri": uri, "digest": "dynamic", "size": None}]
        reference = McpSkillReference(McpSkillIdentity("server", manifest["uri"]), manifest)
        client = McpSkillsClient(_FakeSession([], [SimpleNamespace(blob="%%%")]), origin="server")

        with pytest.raises(McpSkillsClientError, match="invalid base64"):
            await client.read_resource(reference, uri)

    async def test_given_direct_lookup_when_requested_then_returns_origin_bound_manifest(
        self,
    ) -> None:
        manifest = _manifest()
        client = McpSkillsClient(_FakeSession([{"skill": manifest}]), origin="server")

        reference = await client.get_skill(manifest["uri"])

        assert reference.identity == McpSkillIdentity("server", manifest["uri"])

    async def test_given_native_server_when_listed_then_reads_resources_only_on_demand(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill = _write_skill(tmp_path, "alpha")
        server = await create_mcp_server([skill], origin="publisher-a")
        async with Client(server) as client:
            wrapper = McpSkillsClient(client.session, origin="publisher-a")
            original_read = client.session.read_resource
            reads: list[str] = []

            async def tracked_read(uri: str, **kwargs: object):
                reads.append(uri)
                return await original_read(uri, **kwargs)

            monkeypatch.setattr(client.session, "read_resource", tracked_read)

            listed = await wrapper.list_skills()

            assert len(listed) == 1
            reference = listed[0]
            assert reference.identity == McpSkillIdentity("publisher-a", "skill://alpha/SKILL.md")
            assert reads == []
            binary_uri = next(
                resource["uri"]
                for resource in reference.manifest["resources"]
                if resource["uri"].endswith("image.bin")
            )

            assert await wrapper.read_resource(reference, binary_uri) == b"\x00\xff\x80"
            assert reads == [binary_uri]

    async def test_given_same_skill_uri_from_two_origins_then_identities_remain_distinct(
        self, tmp_path: Path
    ) -> None:
        skill = _write_skill(tmp_path, "alpha")
        server = await create_mcp_server([skill])
        async with Client(server) as first_client, Client(server) as second_client:
            first = (await McpSkillsClient(first_client.session, origin="server-a").list_skills())[
                0
            ]
            second = (
                await McpSkillsClient(second_client.session, origin="server-b").list_skills()
            )[0]

        assert first.identity.uri == second.identity.uri
        assert first.identity != second.identity

    async def test_given_invalid_digest_when_resource_read_then_rejects_content(
        self, tmp_path: Path
    ) -> None:
        skill = _write_skill(tmp_path, "alpha")
        server = await create_mcp_server([skill], origin="publisher-a")
        async with Client(server) as client:
            wrapper = McpSkillsClient(client.session, origin="publisher-a")
            reference = (await wrapper.list_skills())[0]
            manifest = deepcopy(reference.manifest)
            asset = next(
                item for item in manifest["resources"] if item["uri"].endswith("image.bin")
            )
            asset["digest"] = "sha256:" + "0" * 64
            tampered = replace(reference, manifest=manifest)

            with pytest.raises(McpSkillsClientError, match="do not match"):
                await wrapper.read_resource(tampered, asset["uri"])

    async def test_given_reference_from_another_origin_when_read_then_rejects_reference(
        self, tmp_path: Path
    ) -> None:
        skill = _write_skill(tmp_path, "alpha")
        server = await create_mcp_server([skill], origin="publisher-a")
        async with Client(server) as client:
            wrapper = McpSkillsClient(client.session, origin="publisher-b")
            reference = (await McpSkillsClient(client.session, origin="publisher-a").list_skills())[
                0
            ]

            with pytest.raises(McpSkillsClientError, match="different MCP origin"):
                await wrapper.read_resource(reference, reference.manifest["uri"])

    async def test_given_page_size_one_when_discovered_then_follows_cursor_pages(
        self, tmp_path: Path
    ) -> None:
        skills = [_write_skill(tmp_path, skill_id) for skill_id in ("alpha", "beta", "gamma")]
        server = await create_mcp_server(skills, page_size=1, origin="publisher")
        async with Client(server) as client:
            references = await McpSkillsClient(client.session, origin="publisher").list_skills()

        assert [ref.identity.uri for ref in references] == [
            "skill://alpha/SKILL.md",
            "skill://beta/SKILL.md",
            "skill://gamma/SKILL.md",
        ]
