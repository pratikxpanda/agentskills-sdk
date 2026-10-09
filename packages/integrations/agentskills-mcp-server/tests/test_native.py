"""Native Skills requests through the official modern MCP client."""

import base64
from pathlib import Path
from typing import Any

import pytest

from agentskills_core import FileAccessNotSupportedError, Skill, SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider


async def _request(client, method: str, **params):
    from mcp.types import Request
    from pydantic import TypeAdapter

    return await client.session.send_request(
        Request[dict[str, Any], str](method=method, params=params), TypeAdapter(dict[str, Any])
    )


def _raw(content) -> bytes:
    text = getattr(content, "text", None)
    return text.encode("utf-8") if text is not None else base64.b64decode(content.blob)


async def _revision(client, uri: str) -> str:
    resources = (await client.list_resources()).resources
    return next(r for r in resources if str(r.uri) == uri).meta["io.agentskills/publication"][
        "revision"
    ]


async def test_given_public_factory_when_connected_then_only_native_skills_are_served():
    from mcp import Client

    import agentskills_mcp_server

    assert not hasattr(agentskills_mcp_server, "AgentSkillsMcpContextProvider")
    server = await agentskills_mcp_server.create_mcp_server([])
    async with Client(server) as client:
        assert client.server_capabilities.extensions == {"io.modelcontextprotocol/skills": {}}
        assert not (await client.list_tools()).tools
        assert (await _request(client, "skills/list"))["skills"] == []


async def test_given_refresh_when_source_changes_then_manifest_and_bytes_change_together(tmp_path):
    from mcp import Client, MCPError

    from agentskills_mcp_server import create_mcp_server

    skills = [_skill(tmp_path, name) for name in ("alpha", "beta")]
    events = []
    server = await create_mcp_server(
        skills, page_size=1, observer=events.append, origin="private-origin"
    )
    async with Client(server) as client:
        first = await _request(client, "skills/list")
        revision = await _revision(client, "skill://alpha/SKILL.md")
        (tmp_path / "alpha" / "new.bin").write_bytes(b"\xff")
        await server.refresh()
        second = await _request(client, "skills/list")
        assert revision != await _revision(client, "skill://alpha/SKILL.md")
        assert "_meta" not in second["skills"][0]
        assert (
            base64.b64decode((await client.read_resource("skill://alpha/new.bin")).contents[0].blob)
            == b"\xff"
        )
        with pytest.raises(MCPError):
            await _request(client, "skills/list", cursor=first["nextCursor"])
        skills.clear()
        await server.refresh()
        assert (await client.list_resources()).resources == []
        with pytest.raises(MCPError):
            await client.read_resource("skill://alpha/new.bin")
    assert server.health()["skillCount"] == 0
    assert {event.operation for event in events} >= {
        "fetch",
        "verification",
        "refresh",
        "discovery",
    }
    assert "private-origin" not in repr(events)


async def test_given_verified_source_when_outage_then_stale_is_visible_and_revocation_withdraws(
    tmp_path, monkeypatch
):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from agentskills_core import ProviderUnavailableError, SkillUnavailableError
    from agentskills_core.policy import publish_snapshot
    from agentskills_core.snapshots import capture_skill
    from agentskills_core.trust import (
        DetachedSignature,
        TrustPolicy,
        VerificationError,
        signature_payload,
    )
    from agentskills_mcp_server import create_mcp_server

    skill = _skill(tmp_path, "alpha")
    snapshot = await capture_skill(skill)
    key = Ed25519PrivateKey.generate()
    trust = TrustPolicy("publisher", {"key": key.public_key().public_bytes_raw()})
    proof = DetachedSignature("key", key.sign(signature_payload(snapshot, origin="publisher")))
    server = await create_mcp_server(
        [skill],
        max_stale_age=60,
        publication_policy=lambda source: publish_snapshot(source, trust=trust, proof=proof),
    )

    async def unavailable(*args, **kwargs):
        raise ProviderUnavailableError("outage")

    monkeypatch.setattr(skill, "read_file", unavailable)
    assert (await server.refresh())["stale"] is True
    contents = await server.read_resource("skill://alpha/SKILL.md")
    assert contents[0].meta["io.agentskills/publication"]["stale"] is True
    trust = TrustPolicy("publisher")
    with pytest.raises(VerificationError):
        await server.refresh()
    assert not server.health()["ready"]
    with pytest.raises(SkillUnavailableError):
        await server.read_resource("skill://alpha/SKILL.md")


async def test_given_remote_helper_without_auth_when_built_then_rejected():
    from agentskills_mcp_server import create_mcp_server

    server = await create_mcp_server([])
    with pytest.raises(ValueError, match="authorization"):
        server.secure_http_app(
            allowed_hosts=["skills.example"], allowed_origins=["https://host.example"]
        )
    with pytest.raises(ValueError, match="explicit"):
        server.secure_http_app(allowed_hosts=["*"], allowed_origins=[])


@pytest.mark.parametrize("change", ["removed_file", "changed_skill", "removed_skill"])
async def test_given_known_change_before_outage_when_refreshed_then_stale_is_forbidden(
    tmp_path, monkeypatch, change
):
    from agentskills_core import ProviderUnavailableError, SkillUnavailableError
    from agentskills_mcp_server import create_mcp_server

    skills = [_skill(tmp_path, name) for name in ("alpha", "beta")]
    (tmp_path / "alpha" / "extra.bin").write_bytes(b"extra")
    server = await create_mcp_server(skills, max_stale_age=60)

    async def unavailable(*args, **kwargs):
        raise ProviderUnavailableError("outage")

    if change == "removed_file":
        (tmp_path / "alpha" / "extra.bin").unlink()
        monkeypatch.setattr(skills[0], "read_file", unavailable)
    elif change == "changed_skill":
        (tmp_path / "alpha" / "extra.bin").write_bytes(b"changed")
        monkeypatch.setattr(skills[1], "read_file", unavailable)
    else:
        skills.pop(0)
        monkeypatch.setattr(skills[0], "read_file", unavailable)

    with pytest.raises(SkillUnavailableError) as caught:
        await server.refresh()
    assert not isinstance(caught.value, ProviderUnavailableError)
    assert not server.health()["ready"]


async def test_given_authorized_http_app_when_origin_or_host_is_invalid_then_rejected():
    import httpx
    from mcp.server.auth.provider import AccessToken
    from mcp.server.auth.settings import AuthSettings

    from agentskills_mcp_server import create_mcp_server

    class Verifier:
        async def verify_token(self, token):
            if token != "accepted":
                return None
            return AccessToken(
                token=token,
                client_id="test",
                scopes=["skills:read"],
                resource="https://skills.example/mcp",
            )

    server = await create_mcp_server(
        [],
        auth=AuthSettings(
            issuer_url="https://identity.example",
            resource_server_url="https://skills.example/mcp",
            required_scopes=["skills:read"],
            validate_token_resource=True,
        ),
        token_verifier=Verifier(),
    )
    app = server.secure_http_app(
        allowed_hosts=["skills.example"], allowed_origins=["https://host.example"]
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://skills.example"
        ) as client,
    ):
        assert (await client.post("/mcp", json={})).status_code == 401
        headers = {"Authorization": "Bearer accepted", "Origin": "https://host.example"}
        assert (
            await client.post("/mcp", json={}, headers={**headers, "Host": "evil.example"})
        ).status_code == 421
        assert (
            await client.post(
                "/mcp", json={}, headers={**headers, "Origin": "https://evil.example"}
            )
        ).status_code == 403


async def test_native_discovery_lookup_and_original_bytes(tmp_path):
    from mcp import Client, MCPError

    from agentskills_mcp_server.native import create_mcp_server

    root = tmp_path / "example"
    root.mkdir()
    raw = (
        b"\xef\xbb\xbf---\r\nname: example\r\ndescription: Example\r\n"
        b"custom: true\r\n---\r\nBody\r\n"
    )
    (root / "SKILL.md").write_bytes(raw)
    (root / "binary.bin").write_bytes(b"\x00\xff")
    server = await create_mcp_server([Skill("example", LocalFileSystemSkillProvider(tmp_path))])
    async with Client(server) as client:
        assert client.server_capabilities.extensions == {"io.modelcontextprotocol/skills": {}}
        assert client.server_capabilities.resources is not None
        listed = await _request(client, "skills/list")
        assert listed["resultType"] == "complete"
        assert listed["ttlMs"] == 0
        assert listed["cacheScope"] == "private"
        entry = listed["skills"][0]
        assert entry["frontmatter"]["custom"] is True
        assert len(entry["resources"]) == 2
        fetched = await _request(client, "skills/get", uri=entry["uri"])
        assert fetched["skill"] == entry
        (root / "SKILL.md").write_bytes(b"changed after capture")
        contents = await client.read_resource(entry["uri"])
        assert _raw(contents.contents[0]) == raw
        assert contents.contents[0].text == raw.decode("utf-8")
        assert contents.result_type == "complete"
        assert contents.ttl_ms == 0
        assert contents.cache_scope == "private"
        with pytest.raises(MCPError) as missing:
            await _request(client, "skills/get", uri="skill://missing/SKILL.md")
        assert missing.value.code == -32602
        with pytest.raises(MCPError) as missing_file:
            await client.read_resource("skill://example/missing.txt")
        assert missing_file.value.code == -32602


def _skill(root: Path, skill_id: str, *, name: str | None = None) -> Skill:
    directory = root / skill_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_bytes(
        f"---\nname: {name or skill_id}\ndescription: Example\n---\nBody\n".encode()
    )
    return Skill(skill_id, LocalFileSystemSkillProvider(root))


async def test_pagination_and_direct_lookup_are_independent(tmp_path):
    from mcp import Client, MCPError

    from agentskills_mcp_server.native import create_mcp_server

    skills = [_skill(tmp_path, name) for name in ("alpha", "beta", "gamma")]
    (tmp_path / "alpha" / "extra.txt").write_bytes(b"supporting file")
    server = await create_mcp_server(skills, page_size=1)
    other_server = await create_mcp_server(skills, page_size=1)
    async with Client(server) as client, Client(other_server) as other:
        direct = await _request(client, "skills/get", uri="skill://gamma/SKILL.md")
        assert direct["skill"]["frontmatter"]["name"] == "gamma"
        assert "nextCursor" not in direct
        first = await _request(client, "skills/list")
        assert len(first["skills"]) == 1
        assert len(first["skills"][0]["resources"]) == 2
        second = await _request(client, "skills/list", cursor=first["nextCursor"])
        third = await _request(client, "skills/list", cursor=second["nextCursor"])
        assert [page["skills"][0]["frontmatter"]["name"] for page in (first, second, third)] == [
            "alpha",
            "beta",
            "gamma",
        ]
        assert "nextCursor" not in third
        for cursor in ("invalid", ""):
            with pytest.raises(MCPError) as error:
                await _request(client, "skills/list", cursor=cursor)
            assert error.value.code == -32602
        with pytest.raises(MCPError) as foreign:
            await _request(other, "skills/list", cursor=first["nextCursor"])
        assert foreign.value.code == -32602


@pytest.mark.parametrize("listed_ids", [[], ["alpha"]])
async def test_partial_or_empty_listing_still_allows_direct_lookup(tmp_path, listed_ids):
    from mcp import Client

    from agentskills_mcp_server.native import create_mcp_server

    server = await create_mcp_server(
        [_skill(tmp_path, name) for name in ("alpha", "beta")], listed_skill_ids=listed_ids
    )
    async with Client(server) as client:
        listed = await _request(client, "skills/list")
        assert [entry["frontmatter"]["name"] for entry in listed["skills"]] == listed_ids
        fetched = await _request(client, "skills/get", uri="skill://beta/SKILL.md")
        assert fetched["skill"]["frontmatter"]["name"] == "beta"


async def test_nested_skills_share_exact_resources_without_duplicate_listing(tmp_path):
    from mcp import Client

    from agentskills_mcp_server.native import create_mcp_server

    parent = _skill(tmp_path, "parent")
    child = _skill(tmp_path / "parent", "child")
    (tmp_path / "parent" / "child" / "raw.bin").write_bytes(b"\xff\x00")
    server = await create_mcp_server([child, parent], skill_paths={"child": "parent/child"})
    async with Client(server) as client:
        listed = await _request(client, "skills/list")
        entries = {entry["uri"]: entry for entry in listed["skills"]}
        assert len(entries) == 2
        parent_files = entries["skill://parent/SKILL.md"]["resources"]
        child_files = entries["skill://parent/child/SKILL.md"]["resources"]
        assert len(parent_files) == 3
        assert len(child_files) == 2
        assert all(file in parent_files for file in child_files)
        resources = (await client.list_resources()).resources
        assert len(resources) == 3
        child_resource = next(
            resource for resource in resources if resource.uri == "skill://parent/child/SKILL.md"
        )
        assert child_resource.name == "child"
        assert child_resource.description == "Example"
        assert child_resource.mime_type == "text/markdown"


async def test_conflicting_nested_capture_fails_before_serving(tmp_path):
    from agentskills_mcp_server.native import create_mcp_server

    parent = _skill(tmp_path, "parent")
    _skill(tmp_path / "parent", "child")
    child = _skill(tmp_path / "other", "child")
    (tmp_path / "other" / "child" / "SKILL.md").write_bytes(
        b"---\nname: child\ndescription: Different capture\n---\n"
    )
    with pytest.raises(ValueError, match="Conflicting captured bytes"):
        await create_mcp_server([parent, child], skill_paths={"child": "parent/child"})


@pytest.mark.parametrize("extra_parent", [False, True])
async def test_nested_capture_membership_must_match(tmp_path, extra_parent):
    from agentskills_mcp_server.native import create_mcp_server

    parent = _skill(tmp_path, "parent")
    _skill(tmp_path / "parent", "child")
    child = _skill(tmp_path / "other", "child")
    extra_root = tmp_path / ("parent" if extra_parent else "other") / "child"
    (extra_root / "extra.txt").write_bytes(b"not present in both captures")
    with pytest.raises(ValueError, match="complete file set"):
        await create_mcp_server([parent, child], skill_paths={"child": "parent/child"})


@pytest.mark.parametrize(
    ("name", "data", "as_text"),
    [
        ("notes.md", b"\xef\xbb\xbf# BOM\r\nline\r\n", True),
        ("script.sh", b"#!/bin/sh\necho hi\n", True),
        ("data.unknown", "caf\u00e9\n".encode(), True),
        ("empty.txt", b"", True),
        ("nul.txt", b"abc\x00def", False),
        ("latin1.txt", b"caf\xe9", False),
        ("image.png", b"\x89PNG\r\n\x1a\n", False),
    ],
)
async def test_text_is_delivered_as_text_only_when_lossless(tmp_path, name, data, as_text):
    from mcp import Client

    from agentskills_mcp_server import create_mcp_server

    skill = _skill(tmp_path, "alpha")
    (tmp_path / "alpha" / name).write_bytes(data)
    server = await create_mcp_server([skill])
    async with Client(server) as client:
        content = (await client.read_resource(f"skill://alpha/{name}")).contents[0]
        assert (getattr(content, "text", None) is not None) is as_text
        assert _raw(content) == data
        listed = next(
            r for r in (await client.list_resources()).resources if str(r.uri).endswith(name)
        )
        assert listed.name == name
        if as_text and "unknown" in name:
            assert listed.mime_type == "text/plain"


async def test_skill_entries_match_the_spec_shape(tmp_path):
    from mcp import Client

    from agentskills_mcp_server import create_mcp_server

    server = await create_mcp_server([_skill(tmp_path, "alpha")])
    async with Client(server) as client:
        entry = (await _request(client, "skills/list"))["skills"][0]
        assert set(entry) == {"uri", "frontmatter", "resources"}
        fetched = await _request(client, "skills/get", uri=entry["uri"])
        assert set(fetched["skill"]) == {"uri", "frontmatter", "resources"}
        assert all(set(item) == {"uri", "digest", "size"} for item in entry["resources"])


async def test_canonical_escaped_uris_are_exact_and_do_not_traverse(tmp_path):
    from mcp import Client, MCPError

    from agentskills_mcp_server.native import create_mcp_server

    skill = _skill(tmp_path, "alias", name="\u00e9tude")
    (tmp_path / "alias" / "raw #%2F.bin").write_bytes(b"\x00\xff")
    server = await create_mcp_server([skill], skill_paths={"alias": "team space/\u00e9tude"})
    async with Client(server) as client:
        entry = (await _request(client, "skills/list"))["skills"][0]
        assert entry["uri"] == "skill://team%20space/%C3%A9tude/SKILL.md"
        raw_uri = "skill://team%20space/%C3%A9tude/raw%20%23%252F.bin"
        contents = await client.read_resource(raw_uri)
        assert base64.b64decode(contents.contents[0].blob) == b"\x00\xff"
        for uri in (
            "skill://team%20space/%C3%A9tude/../SKILL.md",
            "skill://team%20space/%C3%A9tude/%2e%2e/SKILL.md",
            "skill://other/SKILL.md",
        ):
            with pytest.raises(MCPError) as error:
                await client.read_resource(uri)
            assert error.value.code == -32602


async def test_aliases_can_publish_same_name_at_distinct_uris(tmp_path):
    from mcp import Client

    from agentskills_mcp_server.native import create_mcp_server

    handles = [_skill(tmp_path, alias, name="shared") for alias in ("one", "two")]
    server = await create_mcp_server(handles)
    async with Client(server) as client:
        result = await _request(client, "skills/list")
        assert [entry["uri"] for entry in result["skills"]] == [
            "skill://one/shared/SKILL.md",
            "skill://two/shared/SKILL.md",
        ]
    with pytest.raises(ValueError, match="Duplicate canonical"):
        await create_mcp_server(handles, skill_paths={"one": "shared", "two": "shared"})


@pytest.mark.parametrize(
    "options",
    [
        {"page_size": 0},
        {"max_skills": 0},
        {"max_total_bytes": -1},
        {"skill_paths": {"missing": "missing"}},
        {"listed_skill_ids": ["missing"]},
    ],
)
async def test_invalid_publication_options(options):
    from agentskills_mcp_server.native import create_mcp_server

    with pytest.raises(ValueError):
        await create_mcp_server(SkillRegistry(), **options)


async def test_publication_bounds_and_lossless_requirement(tmp_path):
    from agentskills_mcp_server.native import create_mcp_server

    first = _skill(tmp_path, "first")
    second = _skill(tmp_path, "second")
    with pytest.raises(ValueError, match="max_skills"):
        await create_mcp_server([first, second], max_skills=1)
    with pytest.raises(ValueError, match="Duplicate skill IDs"):
        await create_mcp_server([first, first])
    total = sum((tmp_path / name / "SKILL.md").stat().st_size for name in ("first", "second"))
    await create_mcp_server([first, second], max_total_bytes=total)
    with pytest.raises(ValueError, match="byte snapshot limit"):
        await create_mcp_server([first, second], max_total_bytes=total - 1)
    provider = LocalFileSystemSkillProvider(tmp_path)
    provider.supports_file_access = False
    with pytest.raises(FileAccessNotSupportedError):
        await create_mcp_server([Skill("first", provider)])


async def test_empty_registry_and_unsupported_directory_method():
    from mcp import Client, MCPError

    from agentskills_mcp_server.native import create_mcp_server

    server = await create_mcp_server(SkillRegistry())
    async with Client(server) as client:
        assert (await _request(client, "skills/list"))["skills"] == []
        assert (await client.list_tools()).tools == []
        assert client.server_capabilities.extensions == {"io.modelcontextprotocol/skills": {}}
        with pytest.raises(MCPError) as error:
            await _request(client, "resources/directory/read", uri="skill://missing")
        assert error.value.code == -32601


@pytest.mark.parametrize(
    ("method", "params"),
    [("skills/get", {}), ("skills/get", {"uri": None}), ("skills/list", {"cursor": 2})],
)
async def test_invalid_method_params_use_protocol_errors(method, params):
    from mcp import Client, MCPError

    from agentskills_mcp_server.native import create_mcp_server

    server = await create_mcp_server([])
    async with Client(server) as client:
        with pytest.raises(MCPError) as error:
            await _request(client, method, **params)
        assert error.value.code == -32602


async def test_native_methods_reject_legacy_protocol_but_resources_remain_ordinary(tmp_path):
    from mcp import Client, MCPError

    from agentskills_mcp_server.native import create_mcp_server

    server = await create_mcp_server([_skill(tmp_path, "example")])
    async with Client(server, mode="legacy") as client:
        with pytest.raises(MCPError) as error:
            await _request(client, "skills/list")
        assert error.value.code == -32601
        result = await client.read_resource("skill://example/SKILL.md")
        assert b"name: example" in _raw(result.contents[0])


def test_native_builder_is_a_lazy_public_export():
    import agentskills_mcp_server
    from agentskills_mcp_server.native import create_mcp_server

    assert agentskills_mcp_server.create_mcp_server is create_mcp_server


@pytest.mark.parametrize("entrypoint", ["mcp", "tools"])
async def test_native_cli_stdio_roundtrip(tmp_path, entrypoint):
    import asyncio
    import json
    import os
    import sys

    from mcp import Client, StdioServerParameters

    _skill(tmp_path, "example")
    config_path = tmp_path / "server.json"
    config_path.write_text(
        json.dumps(
            {
                "name": "Native CLI",
                "skill_paths": {"example": "team/example"},
                "skills": [{"id": "example", "provider": "fs", "options": {"root": str(tmp_path)}}],
            }
        ),
        encoding="utf-8",
    )
    if entrypoint == "tools":
        arguments = ["-m", "agentskills_tools", "serve", str(tmp_path)]
        expected_uri = "skill://example/SKILL.md"
    else:
        arguments = ["-m", "agentskills_mcp_server", "--config", str(config_path)]
        expected_uri = "skill://team/example/SKILL.md"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=arguments,
        env={"PYTHONPATH": os.environ.get("PYTHONPATH", "")},
    )
    process = await asyncio.create_subprocess_exec(
        parameters.command,
        *arguments,
        "--check",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, errors = await asyncio.wait_for(process.communicate(), timeout=20)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert process.returncode == 0, errors.decode()
    if entrypoint == "mcp":
        report = json.loads(output)
        assert report["status"] == "ready"
        assert report["requiresProtocol"] == "2026-07-28"
        assert report["transportTested"] is False
    else:
        assert b"Publication ready" in output
    async with asyncio.timeout(20), Client(parameters) as client:
        assert client.server_capabilities.extensions == {"io.modelcontextprotocol/skills": {}}
        result = await _request(client, "skills/list")
        entry = result["skills"][0]
        assert entry["uri"] == expected_uri
        contents = await client.read_resource(entry["uri"])
        assert _raw(contents.contents[0]) == (tmp_path / "example" / "SKILL.md").read_bytes()


async def _native_http_roundtrip(tmp_path, json_response, *, timeout=20):
    import asyncio
    import hashlib
    import socket

    import uvicorn
    from mcp import Client

    from agentskills_mcp_server.native import create_mcp_server

    skill = _skill(tmp_path, "example")
    (tmp_path / "example" / "raw.bin").write_bytes(b"\x00\xff\r\n")
    expected = {
        f"skill://example/{path.name}": path.read_bytes()
        for path in (tmp_path / "example").iterdir()
    }
    server = await create_mcp_server([skill])
    started = asyncio.Event()

    class ListeningServer(uvicorn.Server):
        async def startup(self, sockets: list[socket.socket] | None = None) -> None:
            await super().startup(sockets=sockets)
            started.set()

    app = server.streamable_http_app(json_response=json_response)
    http_server = ListeningServer(
        uvicorn.Config(app, log_level="error", lifespan="on", timeout_graceful_shutdown=1)
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        async with asyncio.TaskGroup() as tasks:
            server_task = tasks.create_task(http_server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(timeout):
                    await started.wait()
                    async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                        assert client.server_capabilities.extensions == {
                            "io.modelcontextprotocol/skills": {}
                        }
                        entry = (await _request(client, "skills/list"))["skills"][0]
                        assert {resource["uri"] for resource in entry["resources"]} == set(expected)
                        fetched = await _request(client, "skills/get", uri=entry["uri"])
                        assert fetched["skill"] == entry
                        for resource in entry["resources"]:
                            result = await client.read_resource(resource["uri"])
                            raw = _raw(result.contents[0])
                            assert raw == expected[resource["uri"]]
                            assert resource["size"] == len(raw)
                            assert resource["digest"] == f"sha256:{hashlib.sha256(raw).hexdigest()}"
                            assert result.result_type == "complete"
                            assert result.ttl_ms == 0
                            assert result.cache_scope == "private"
            finally:
                http_server.should_exit = True
                await asyncio.wait_for(asyncio.shield(server_task), timeout=5)


@pytest.mark.parametrize("json_response", [False, True])
async def test_native_streamable_http_roundtrip(tmp_path, json_response):
    await _native_http_roundtrip(tmp_path, json_response)


@pytest.mark.parametrize("failure", ["assertion", "cancellation", "timeout"])
async def test_native_http_shutdown_after_client_failure(tmp_path, monkeypatch, failure):
    import asyncio

    import uvicorn
    from mcp import Client

    existing_tasks = asyncio.all_tasks()
    servers = []

    class ObservedServer(uvicorn.Server):
        async def serve(self, sockets=None):
            servers.append((self, list(sockets or [])))
            await super().serve(sockets=sockets)

    async def fail_read(*args, **kwargs):
        if failure == "assertion":
            raise AssertionError("injected client failure")
        if failure == "cancellation":
            asyncio.current_task().cancel()
        await asyncio.Event().wait()

    monkeypatch.setattr(uvicorn, "Server", ObservedServer)
    monkeypatch.setattr(Client, "read_resource", fail_read)
    client_task = asyncio.create_task(
        _native_http_roundtrip(tmp_path, False, timeout=1 if failure == "timeout" else 20)
    )
    if failure == "assertion":
        with pytest.RaisesGroup(
            pytest.RaisesExc(AssertionError, match="injected client failure"),
            flatten_subgroups=True,
        ):
            await client_task
    elif failure == "cancellation":
        with pytest.raises(asyncio.CancelledError):
            await client_task
    else:
        with pytest.RaisesGroup(TimeoutError, flatten_subgroups=True):
            await client_task
    assert len(servers) == 1
    server, listeners = servers[0]
    assert all(listener.fileno() == -1 for listener in listeners)
    assert server.lifespan.shutdown_event.is_set()
    assert not server.server_state.tasks
    assert not server.server_state.connections
    assert asyncio.all_tasks() <= existing_tasks


@pytest.mark.parametrize("fails", [False, True])
def test_native_cli_closes_owned_providers(tmp_path, monkeypatch, fails):
    import json
    import sys
    from unittest.mock import AsyncMock, MagicMock

    import agentskills_mcp_server
    from agentskills_mcp_server.__main__ import main

    _skill(tmp_path, "example")
    provider = LocalFileSystemSkillProvider(tmp_path)
    close = AsyncMock()
    monkeypatch.setattr(provider, "aclose", close, raising=False)
    monkeypatch.setattr("agentskills_mcp_server.config._resolve_provider", lambda *args: provider)
    server = MagicMock()
    builder = AsyncMock(
        return_value=server, side_effect=ValueError("capture failed") if fails else None
    )
    monkeypatch.setattr(agentskills_mcp_server, "create_mcp_server", builder)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "name": "Owned providers",
                "instructions": "Explicit instructions",
                "skills": [{"id": "example", "provider": "fs"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["server", "--config", str(config_path)])
    if fails:
        with pytest.raises(ValueError, match="capture failed"):
            main()
        server.run.assert_not_called()
    else:
        main()
        server.run.assert_called_once_with(transport="stdio")
        assert builder.await_args.kwargs["instructions"] == "Explicit instructions"
    close.assert_awaited_once()
