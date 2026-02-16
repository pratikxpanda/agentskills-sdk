"""Tests for HTTPStaticFileSkillProvider."""

import warnings

import httpx
import pytest
import respx

from agentskills_core import AgentSkillsError, ResourceNotFoundError, SkillNotFoundError
from agentskills_http import HTTPStaticFileSkillProvider
from agentskills_http.static import DEFAULT_TIMEOUT_SECONDS

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


class TestSecurity:
    """Tests for security hardening features."""

    def test_require_tls_rejects_http(self):
        with pytest.raises(ValueError, match="require_tls"):
            HTTPStaticFileSkillProvider("http://example.com/skills", require_tls=True)

    def test_require_tls_allows_https(self):
        provider = HTTPStaticFileSkillProvider(BASE, require_tls=True)
        assert provider._base_url == BASE

    def test_http_url_emits_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            provider = HTTPStaticFileSkillProvider("http://example.com/skills")
            assert len(w) == 1
            assert "unencrypted HTTP" in str(w[0].message)
            # Cleanup
            import asyncio

            asyncio.get_event_loop().run_until_complete(provider.aclose())

    def test_https_url_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            HTTPStaticFileSkillProvider(BASE)
            assert len(w) == 0

    def test_default_timeout_set(self):
        provider = HTTPStaticFileSkillProvider(BASE)
        timeout = provider._client.timeout
        assert timeout.connect == DEFAULT_TIMEOUT_SECONDS
        assert timeout.read == DEFAULT_TIMEOUT_SECONDS

    def test_follow_redirects_disabled(self):
        provider = HTTPStaticFileSkillProvider(BASE)
        assert provider._client.follow_redirects is False

    def test_custom_max_response_bytes(self):
        provider = HTTPStaticFileSkillProvider(BASE, max_response_bytes=1024)
        assert provider._max_response_bytes == 1024

    @respx.mock
    async def test_oversized_response_rejected_text(self):
        huge = "x" * 100
        respx.get(f"{BASE}/big/SKILL.md").respond(text=huge)
        async with HTTPStaticFileSkillProvider(BASE, max_response_bytes=50) as provider:
            with pytest.raises(AgentSkillsError, match="exceeds maximum size"):
                await provider.get_metadata("big")

    @respx.mock
    async def test_oversized_response_rejected_bytes(self):
        respx.get(f"{BASE}/test-skill/scripts/big.sh").respond(content=b"x" * 100)
        async with HTTPStaticFileSkillProvider(BASE, max_response_bytes=50) as provider:
            with pytest.raises(AgentSkillsError, match="exceeds maximum size"):
                await provider.get_script("test-skill", "big.sh")

    async def test_invalid_skill_id_rejected(self):
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(ValueError, match="Invalid skill_id"):
                await provider.get_metadata("../../etc")

    async def test_invalid_resource_name_rejected(self):
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(ValueError, match="Invalid resource name"):
                await provider.get_script("test-skill", "../../../etc/passwd")

    async def test_path_separator_in_skill_id_rejected(self):
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(ValueError, match="Invalid skill_id"):
                await provider.get_metadata("foo/bar")

    @respx.mock
    async def test_error_messages_do_not_leak_url(self):
        respx.get(f"{BASE}/secret-skill/SKILL.md").respond(status_code=403)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(AgentSkillsError, match="403") as exc_info:
                await provider.get_metadata("secret-skill")
            # Error message should NOT contain the base URL
            assert BASE not in str(exc_info.value)


class TestSecurityEdgeCases:
    """Additional edge-case and boundary tests for HTTP provider security."""

    @respx.mock
    async def test_aclose_idempotent(self):
        """Calling aclose() twice should not raise."""
        respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        provider = HTTPStaticFileSkillProvider(BASE)
        await provider.get_metadata("test-skill")
        await provider.aclose()
        await provider.aclose()  # Second call should not raise

    @respx.mock
    async def test_async_context_manager(self):
        """async with enters and exits cleanly."""
        respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            meta = await provider.get_metadata("test-skill")
            assert meta["name"] == "test-skill"
        # After exit, the owned client should be closed
        assert provider._client.is_closed

    @respx.mock
    async def test_response_exactly_at_max_passes(self):
        """Response exactly at max_response_bytes boundary should pass."""
        limit = 100
        content = "x" * limit
        respx.get(f"{BASE}/exact/SKILL.md").respond(text=content)
        async with HTTPStaticFileSkillProvider(BASE, max_response_bytes=limit) as provider:
            # Should not raise — exactly at the limit
            text = await provider.get_body("exact")
            assert len(text) == limit

    async def test_empty_string_identifier_rejected(self):
        """Empty string skill_id is rejected by _validate_identifier."""
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(ValueError, match="Invalid skill_id"):
                await provider.get_metadata("")

    @pytest.mark.parametrize(
        "bad_id",
        [
            ".hidden",
            "-leading-hyphen",
            "has space",
            "has/slash",
            "has\\backslash",
            "\u00fcnicode",
        ],
    )
    async def test_invalid_identifier_patterns(self, bad_id: str):
        """Various invalid identifier patterns are all rejected."""
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(ValueError, match="Invalid skill_id"):
                await provider.get_metadata(bad_id)

    @respx.mock
    async def test_valid_identifier_with_dots_and_hyphens(self):
        """Identifiers with dots and hyphens (like 'my-skill.v2') should be accepted."""
        respx.get(f"{BASE}/my-skill.v2/SKILL.md").respond(
            text="---\nname: my-skill.v2\ndescription: Desc.\n---\n# Body"
        )
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            meta = await provider.get_metadata("my-skill.v2")
            assert meta["name"] == "my-skill.v2"

    def test_https_url_does_not_warn_or_raise(self):
        """HTTPS URL with require_tls should not warn or raise."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            provider = HTTPStaticFileSkillProvider(BASE, require_tls=True)
            assert len(w) == 0
            assert provider._base_url == BASE
