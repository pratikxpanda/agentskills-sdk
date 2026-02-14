"""Tests for HTTPStaticFileSkillProvider."""

import httpx
import pytest
import respx

from agentskills_core import AgentSkillsError, ResourceNotFoundError, SkillNotFoundError
from agentskills_http import HTTPStaticFileSkillProvider

BASE = "https://skills.example.com"

SKILL_MD = """\
---
name: test-skill
description: A skill for unit testing.
---
# Test Skill

This is the body of the test skill.
"""


def _mock_skill_routes(router: respx.MockRouter) -> None:
    """Register standard mock routes for a single test skill."""
    router.get(f"{BASE}/test-skill/SKILL.md").respond(
        text=SKILL_MD,
    )
    router.get(f"{BASE}/test-skill/scripts/run.sh").respond(
        content=b"#!/bin/bash\necho hello",
    )
    router.get(f"{BASE}/test-skill/assets/diagram.mermaid").respond(
        content=b"graph TD; A-->B",
    )
    router.get(f"{BASE}/test-skill/references/sev.md").respond(
        content=b"# Severity\n\nSEV1 is critical.",
    )
    router.get(f"{BASE}/test-skill/references/esc.md").respond(
        content=b"# Escalation Policy",
    )


class TestMetadataAndBody:
    @respx.mock
    async def test_get_metadata(self):
        respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            meta = await provider.get_metadata("test-skill")
        assert meta["name"] == "test-skill"
        assert "unit testing" in meta["description"]

    @respx.mock
    async def test_get_body(self):
        respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            body = await provider.get_body("test-skill")
        assert "# Test Skill" in body
        assert "body of the test skill" in body
        assert "---" not in body

    @respx.mock
    async def test_no_frontmatter(self):
        respx.get(f"{BASE}/bare/SKILL.md").respond(text="# Just body.")
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            meta = await provider.get_metadata("bare")
        assert meta == {}

    @respx.mock
    async def test_missing_skill_raises(self):
        respx.get(f"{BASE}/nonexistent/SKILL.md").respond(status_code=404)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(SkillNotFoundError):
                await provider.get_metadata("nonexistent")

    @respx.mock
    async def test_malformed_yaml_fallback(self):
        bad = "---\n: :\ninvalid yaml{{{\n---\n# Body"
        respx.get(f"{BASE}/bad/SKILL.md").respond(text=bad)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            meta = await provider.get_metadata("bad")
        assert meta == {}


class TestScripts:
    @respx.mock
    async def test_get_script(self):
        respx.get(f"{BASE}/test-skill/scripts/run.sh").respond(
            content=b"#!/bin/bash\necho hello",
        )
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            data = await provider.get_script("test-skill", "run.sh")
        assert b"#!/bin/bash" in data

    @respx.mock
    async def test_get_script_missing_raises(self):
        respx.get(f"{BASE}/test-skill/scripts/nope.sh").respond(status_code=404)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(ResourceNotFoundError):
                await provider.get_script("test-skill", "nope.sh")


class TestAssets:
    @respx.mock
    async def test_get_asset(self):
        respx.get(f"{BASE}/test-skill/assets/diagram.mermaid").respond(
            content=b"graph TD; A-->B",
        )
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            data = await provider.get_asset("test-skill", "diagram.mermaid")
        assert data == b"graph TD; A-->B"


class TestReferences:
    @respx.mock
    async def test_get_reference(self):
        respx.get(f"{BASE}/test-skill/references/sev.md").respond(
            content=b"# Severity\n\nSEV1 is critical.",
        )
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            data = await provider.get_reference("test-skill", "sev.md")
        assert b"SEV1" in data

    @respx.mock
    async def test_get_reference_missing_raises(self):
        respx.get(f"{BASE}/test-skill/references/nope.md").respond(status_code=404)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(ResourceNotFoundError):
                await provider.get_reference("test-skill", "nope.md")


class TestClientLifecycle:
    @respx.mock
    async def test_external_client_not_closed(self):
        respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        client = httpx.AsyncClient()
        provider = HTTPStaticFileSkillProvider(BASE, client=client)
        await provider.get_metadata("test-skill")
        await provider.aclose()
        # client should still be open
        assert not client.is_closed
        await client.aclose()

    def test_trailing_slash_stripped(self):
        provider = HTTPStaticFileSkillProvider(f"{BASE}/")
        assert provider._base_url == BASE

    @respx.mock
    async def test_custom_headers(self):
        route = respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        async with HTTPStaticFileSkillProvider(
            BASE, headers={"Authorization": "Bearer tok"}
        ) as provider:
            await provider.get_metadata("test-skill")
        assert route.calls[0].request.headers["Authorization"] == "Bearer tok"

    def test_headers_and_client_conflict(self):
        client = httpx.AsyncClient()
        with pytest.raises(ValueError, match="Cannot specify both"):
            HTTPStaticFileSkillProvider(BASE, client=client, headers={"X-Key": "v"})

    def test_params_and_client_conflict(self):
        client = httpx.AsyncClient()
        with pytest.raises(ValueError, match="Cannot specify both"):
            HTTPStaticFileSkillProvider(BASE, client=client, params={"sig": "abc"})

    @respx.mock
    async def test_custom_params(self):
        route = respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        async with HTTPStaticFileSkillProvider(
            BASE, params={"sv": "2020", "sig": "abc"}
        ) as provider:
            await provider.get_metadata("test-skill")
        request_url = str(route.calls[0].request.url)
        assert "sv=2020" in request_url
        assert "sig=abc" in request_url


class TestHTTPErrors:
    """Tests for non-404 HTTP errors and connection failures."""

    @respx.mock
    async def test_server_error_on_skill_md_raises_agentskills_error(self):
        respx.get(f"{BASE}/broken/SKILL.md").respond(status_code=500)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(AgentSkillsError, match="500"):
                await provider.get_metadata("broken")

    @respx.mock
    async def test_forbidden_on_skill_md_raises_agentskills_error(self):
        respx.get(f"{BASE}/secret/SKILL.md").respond(status_code=403)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(AgentSkillsError, match="403"):
                await provider.get_metadata("secret")

    @respx.mock
    async def test_server_error_on_resource_raises_agentskills_error(self):
        respx.get(f"{BASE}/test-skill/scripts/run.sh").respond(status_code=500)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(AgentSkillsError, match="500"):
                await provider.get_script("test-skill", "run.sh")

    @respx.mock
    async def test_connection_error_on_skill_md(self):
        respx.get(f"{BASE}/fail/SKILL.md").mock(side_effect=httpx.ConnectError("refused"))
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(AgentSkillsError, match="HTTP request failed"):
                await provider.get_metadata("fail")

    @respx.mock
    async def test_connection_error_on_resource(self):
        respx.get(f"{BASE}/test-skill/assets/x.png").mock(side_effect=httpx.ConnectError("refused"))
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(AgentSkillsError, match="HTTP request failed"):
                await provider.get_asset("test-skill", "x.png")


class TestIntegration:
    """Full round-trip with all routes mocked."""

    @respx.mock
    async def test_full_flow(self):
        _mock_skill_routes(respx)

        async with HTTPStaticFileSkillProvider(BASE) as provider:
            # Metadata
            meta = await provider.get_metadata("test-skill")
            assert meta["name"] == "test-skill"

            # Body
            body = await provider.get_body("test-skill")
            assert "# Test Skill" in body

            # Scripts
            script_data = await provider.get_script("test-skill", "run.sh")
            assert b"echo hello" in script_data

            # Assets
            asset_data = await provider.get_asset("test-skill", "diagram.mermaid")
            assert asset_data == b"graph TD; A-->B"

            # References
            ref_data = await provider.get_reference("test-skill", "sev.md")
            assert b"SEV1" in ref_data
