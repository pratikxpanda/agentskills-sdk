"""Tests for HTTPStaticFileSkillProvider."""

import logging
import traceback
import warnings
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
import respx

from agentskills_core import (
    AgentSkillsError,
    DiscoveryNotSupportedError,
    ResourceListingNotSupportedError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillRegistry,
    SkillUnavailableError,
)
from agentskills_http import HTTPStaticFileSkillProvider
from agentskills_http import static as static_module
from agentskills_http.static import DEFAULT_TIMEOUT_SECONDS

BASE = "https://skills.example.com"

SECRET_HEADERS = {"Authorization": "Bearer SUPERSECRETBEARER"}
SECRET_PARAMS = {"sv": "2024-01-01", "sig": "SUPERSECRETSAS"}

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
        async with HTTPStaticFileSkillProvider(BASE, max_retries=0) as provider:
            with pytest.raises(SkillUnavailableError, match="500"):
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
        async with HTTPStaticFileSkillProvider(BASE, max_retries=0) as provider:
            with pytest.raises(SkillUnavailableError, match="500"):
                await provider.get_script("test-skill", "run.sh")

    @respx.mock
    async def test_connection_error_on_skill_md(self):
        respx.get(f"{BASE}/fail/SKILL.md").mock(side_effect=httpx.ConnectError("refused"))
        async with HTTPStaticFileSkillProvider(BASE, max_retries=0) as provider:
            with pytest.raises(SkillUnavailableError, match="ConnectError"):
                await provider.get_metadata("fail")

    @respx.mock
    async def test_connection_error_on_resource(self):
        respx.get(f"{BASE}/test-skill/assets/x.png").mock(side_effect=httpx.ConnectError("refused"))
        async with HTTPStaticFileSkillProvider(BASE, max_retries=0) as provider:
            with pytest.raises(SkillUnavailableError, match="ConnectError"):
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
        provider._owns_client = False

    def test_http_url_emits_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            provider = HTTPStaticFileSkillProvider("http://example.com/skills")
            assert len(w) == 1
            assert "unencrypted HTTP" in str(w[0].message)
            # Provider owns an AsyncClient — mark it as not-owned so
            # garbage collection doesn't warn about unclosed resources.
            provider._owns_client = False

    def test_https_url_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            provider = HTTPStaticFileSkillProvider(BASE)
            assert len(w) == 0
            provider._owns_client = False

    def test_default_timeout_set(self):
        provider = HTTPStaticFileSkillProvider(BASE)
        timeout = provider._client.timeout
        assert timeout.connect == DEFAULT_TIMEOUT_SECONDS
        assert timeout.read == DEFAULT_TIMEOUT_SECONDS
        provider._owns_client = False

    def test_follow_redirects_disabled(self):
        provider = HTTPStaticFileSkillProvider(BASE)
        assert provider._client.follow_redirects is False
        provider._owns_client = False

    def test_custom_max_response_bytes(self):
        provider = HTTPStaticFileSkillProvider(BASE, max_response_bytes=1024)
        assert provider._max_response_bytes == 1024
        provider._owns_client = False

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
            with pytest.raises(SkillNotFoundError, match="Invalid skill_id"):
                await provider.get_metadata("../../etc")

    async def test_invalid_resource_name_rejected(self):
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(ResourceNotFoundError, match="Invalid resource name"):
                await provider.get_script("test-skill", "../../../etc/passwd")

    async def test_path_separator_in_skill_id_rejected(self):
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(SkillNotFoundError, match="Invalid skill_id"):
                await provider.get_metadata("foo/bar")

    @respx.mock
    async def test_error_messages_do_not_leak_url(self):
        respx.get(f"{BASE}/secret-skill/SKILL.md").respond(status_code=403)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(AgentSkillsError, match="403") as exc_info:
                await provider.get_metadata("secret-skill")
            # Error message should NOT contain the base URL
            assert BASE not in str(exc_info.value)

    @respx.mock
    async def test_credentials_do_not_leak_through_the_exception_chain(self):
        """The whole chain must be clean, not just the message we build.

        ``httpx.HTTPStatusError`` renders the full request URL, query
        string included, so chaining it leaked SAS tokens into every
        traceback. The cause is now suppressed.
        """
        secret = "sv=2024-01-01&sig=SUPERSECRETTOKEN"
        respx.get(f"{BASE}/secret-skill/SKILL.md").respond(status_code=403)
        async with HTTPStaticFileSkillProvider(
            BASE, params={"sv": "2024-01-01", "sig": "SUPERSECRETTOKEN"}
        ) as provider:
            with pytest.raises(AgentSkillsError) as exc_info:
                await provider.get_metadata("secret-skill")

        rendered = "".join(
            traceback.format_exception(type(exc_info.value), exc_info.value, exc_info.tb)
        )
        assert "SUPERSECRETTOKEN" not in rendered
        assert secret not in rendered

    @respx.mock
    async def test_credentials_do_not_leak_on_transport_failure(self):
        respx.get(f"{BASE}/fail/SKILL.md").mock(side_effect=httpx.ConnectError("refused"))
        async with HTTPStaticFileSkillProvider(
            BASE, params={"sig": "SUPERSECRETTOKEN"}, max_retries=0
        ) as provider:
            with pytest.raises(SkillUnavailableError) as exc_info:
                await provider.get_metadata("fail")

        rendered = "".join(
            traceback.format_exception(type(exc_info.value), exc_info.value, exc_info.tb)
        )
        assert "SUPERSECRETTOKEN" not in rendered


class TestLogRecordsCarryNoSecrets:
    """A log file outlives a traceback, so it is the harder guarantee."""

    @staticmethod
    def _assert_clean(caplog):
        assert "SUPERSECRETBEARER" not in caplog.text
        assert "SUPERSECRETSAS" not in caplog.text
        assert BASE not in caplog.text

    @respx.mock
    async def test_successful_fetch(self, caplog):
        _mock_skill_routes(respx.mock)
        with caplog.at_level(logging.DEBUG, logger="agentskills"):
            async with HTTPStaticFileSkillProvider(
                BASE, headers=SECRET_HEADERS, params=SECRET_PARAMS
            ) as provider:
                await provider.get_metadata("test-skill")
                await provider.get_script("test-skill", "run.sh")
        assert caplog.text  # the test is worthless if nothing was logged
        self._assert_clean(caplog)

    @respx.mock
    async def test_retry_warning(self, caplog):
        respx.get(f"{BASE}/flaky/SKILL.md").respond(status_code=503)
        with caplog.at_level(logging.DEBUG, logger="agentskills"):
            async with HTTPStaticFileSkillProvider(
                BASE,
                headers=SECRET_HEADERS,
                params=SECRET_PARAMS,
                max_retries=2,
                retry_backoff=0.001,
            ) as provider:
                with pytest.raises(SkillUnavailableError):
                    await provider.get_metadata("flaky")
        assert "Retrying" in caplog.text
        self._assert_clean(caplog)

    @respx.mock
    async def test_transport_failure(self, caplog):
        respx.get(f"{BASE}/fail/SKILL.md").mock(side_effect=httpx.ConnectError("refused"))
        with caplog.at_level(logging.DEBUG, logger="agentskills"):
            async with HTTPStaticFileSkillProvider(
                BASE,
                headers=SECRET_HEADERS,
                params=SECRET_PARAMS,
                max_retries=1,
                retry_backoff=0.001,
            ) as provider:
                with pytest.raises(SkillUnavailableError):
                    await provider.get_metadata("fail")
        self._assert_clean(caplog)

    @respx.mock
    async def test_registration_and_catalog(self, caplog):
        _mock_skill_routes(respx.mock)
        with caplog.at_level(logging.DEBUG, logger="agentskills"):
            async with HTTPStaticFileSkillProvider(
                BASE, headers=SECRET_HEADERS, params=SECRET_PARAMS
            ) as provider:
                registry = SkillRegistry()
                await registry.register("test-skill", provider)
                await registry.get_skills_catalog()
        assert "Registered skill" in caplog.text
        self._assert_clean(caplog)


class TestErrorClassification:
    """404 is a fact about the skill; 503 is a fact about the server."""

    @respx.mock
    async def test_410_is_not_found(self):
        respx.get(f"{BASE}/gone/SKILL.md").respond(status_code=410)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(SkillNotFoundError):
                await provider.get_metadata("gone")

    @pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
    @respx.mock
    async def test_retryable_statuses_are_unavailable(self, status):
        respx.get(f"{BASE}/flaky/SKILL.md").respond(status_code=status)
        async with HTTPStaticFileSkillProvider(BASE, max_retries=0) as provider:
            with pytest.raises(SkillUnavailableError, match=str(status)):
                await provider.get_metadata("flaky")

    @respx.mock
    async def test_unavailable_is_not_confused_with_not_found(self):
        """The whole point: a 503 must not tell the caller the skill is gone."""
        respx.get(f"{BASE}/flaky/SKILL.md").respond(status_code=503)
        async with HTTPStaticFileSkillProvider(BASE, max_retries=0) as provider:
            with pytest.raises(SkillUnavailableError) as exc_info:
                await provider.get_metadata("flaky")
        assert not isinstance(exc_info.value, SkillNotFoundError)

    @respx.mock
    async def test_client_error_is_not_retryable(self):
        respx.get(f"{BASE}/bad/SKILL.md").respond(status_code=400)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(AgentSkillsError, match="400") as exc_info:
                await provider.get_metadata("bad")
        assert not isinstance(exc_info.value, SkillUnavailableError)

    @respx.mock
    async def test_unauthorised_explains_without_echoing_credentials(self):
        respx.get(f"{BASE}/secret/SKILL.md").respond(status_code=401)
        async with HTTPStaticFileSkillProvider(
            BASE, params={"sig": "SUPERSECRETTOKEN"}
        ) as provider:
            with pytest.raises(AgentSkillsError, match="unauthorised") as exc_info:
                await provider.get_metadata("secret")
        assert "SUPERSECRETTOKEN" not in str(exc_info.value)

    @respx.mock
    async def test_timeout_is_unavailable(self):
        respx.get(f"{BASE}/slow/SKILL.md").mock(side_effect=httpx.ReadTimeout("too slow"))
        async with HTTPStaticFileSkillProvider(BASE, max_retries=0) as provider:
            with pytest.raises(SkillUnavailableError, match="ReadTimeout"):
                await provider.get_metadata("slow")


class TestRetries:
    @respx.mock
    async def test_retries_then_succeeds(self):
        route = respx.get(f"{BASE}/test-skill/SKILL.md").mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(503),
                httpx.Response(200, text=SKILL_MD),
            ]
        )
        async with HTTPStaticFileSkillProvider(
            BASE, max_retries=2, retry_backoff=0.001
        ) as provider:
            assert "# Test Skill" in await provider.get_body("test-skill")
        assert route.call_count == 3

    @respx.mock
    async def test_retries_are_bounded(self):
        route = respx.get(f"{BASE}/flaky/SKILL.md").respond(status_code=503)
        async with HTTPStaticFileSkillProvider(
            BASE, max_retries=2, retry_backoff=0.001
        ) as provider:
            with pytest.raises(SkillUnavailableError):
                await provider.get_metadata("flaky")
        assert route.call_count == 3

    @respx.mock
    async def test_not_found_is_never_retried(self):
        route = respx.get(f"{BASE}/missing/SKILL.md").respond(status_code=404)
        async with HTTPStaticFileSkillProvider(BASE, retry_backoff=0.001) as provider:
            with pytest.raises(SkillNotFoundError):
                await provider.get_metadata("missing")
        assert route.call_count == 1

    @respx.mock
    async def test_forbidden_is_never_retried(self):
        route = respx.get(f"{BASE}/secret/SKILL.md").respond(status_code=403)
        async with HTTPStaticFileSkillProvider(BASE, retry_backoff=0.001) as provider:
            with pytest.raises(AgentSkillsError):
                await provider.get_metadata("secret")
        assert route.call_count == 1

    @respx.mock
    async def test_max_retries_zero_disables_retrying(self):
        route = respx.get(f"{BASE}/flaky/SKILL.md").respond(status_code=503)
        async with HTTPStaticFileSkillProvider(BASE, max_retries=0) as provider:
            with pytest.raises(SkillUnavailableError):
                await provider.get_metadata("flaky")
        assert route.call_count == 1

    @respx.mock
    async def test_retry_after_seconds_is_honoured(self, monkeypatch):
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(static_module.asyncio, "sleep", fake_sleep)
        respx.get(f"{BASE}/test-skill/SKILL.md").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "7"}),
                httpx.Response(200, text=SKILL_MD),
            ]
        )
        async with HTTPStaticFileSkillProvider(BASE, max_retries=1) as provider:
            await provider.get_body("test-skill")

        assert slept == [7.0]

    @respx.mock
    async def test_retry_after_http_date_is_honoured(self, monkeypatch):
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(static_module.asyncio, "sleep", fake_sleep)
        when = datetime.now(UTC) + timedelta(seconds=5)
        respx.get(f"{BASE}/test-skill/SKILL.md").mock(
            side_effect=[
                httpx.Response(503, headers={"Retry-After": format_datetime(when, usegmt=True)}),
                httpx.Response(200, text=SKILL_MD),
            ]
        )
        async with HTTPStaticFileSkillProvider(BASE, max_retries=1) as provider:
            await provider.get_body("test-skill")

        assert len(slept) == 1
        assert 3.0 <= slept[0] <= 6.0

    @respx.mock
    async def test_retry_after_beyond_the_cap_fails_fast(self, monkeypatch):
        """Blocking a request path for an hour is worse than failing."""
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(static_module.asyncio, "sleep", fake_sleep)
        route = respx.get(f"{BASE}/flaky/SKILL.md").respond(
            status_code=429, headers={"Retry-After": "3600"}
        )
        async with HTTPStaticFileSkillProvider(BASE, max_retries=3, max_retry_delay=30) as provider:
            with pytest.raises(SkillUnavailableError) as exc_info:
                await provider.get_metadata("flaky")

        assert slept == []
        assert route.call_count == 1
        assert exc_info.value.retry_after == 3600

    @respx.mock
    async def test_backoff_is_jittered_and_grows(self, monkeypatch):
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(static_module.asyncio, "sleep", fake_sleep)
        # Full jitter: assert the bound, not the value.
        monkeypatch.setattr(static_module.random, "uniform", lambda a, b: b)
        respx.get(f"{BASE}/flaky/SKILL.md").respond(status_code=503)
        async with HTTPStaticFileSkillProvider(BASE, max_retries=3, retry_backoff=1.0) as provider:
            with pytest.raises(SkillUnavailableError):
                await provider.get_metadata("flaky")

        assert slept == [1.0, 2.0, 4.0]

    @respx.mock
    async def test_sleep_is_capped_by_max_retry_delay(self, monkeypatch):
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(static_module.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(static_module.random, "uniform", lambda a, b: b)
        respx.get(f"{BASE}/flaky/SKILL.md").respond(status_code=503)
        async with HTTPStaticFileSkillProvider(
            BASE, max_retries=3, retry_backoff=10.0, max_retry_delay=15.0
        ) as provider:
            with pytest.raises(SkillUnavailableError):
                await provider.get_metadata("flaky")

        assert slept == [10.0, 15.0, 15.0]

    def test_rejects_invalid_retry_settings(self):
        with pytest.raises(ValueError, match="max_retries"):
            HTTPStaticFileSkillProvider(BASE, max_retries=-1)
        with pytest.raises(ValueError, match="retry_backoff"):
            HTTPStaticFileSkillProvider(BASE, retry_backoff=0)
        with pytest.raises(ValueError, match="max_retry_delay"):
            HTTPStaticFileSkillProvider(BASE, max_retry_delay=0)


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
            with pytest.raises(SkillNotFoundError, match="Invalid skill_id"):
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
            with pytest.raises(SkillNotFoundError, match="Invalid skill_id"):
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
            provider._owns_client = False


class TestSkillMdCaching:
    @respx.mock
    async def test_single_request_across_a_full_session(self):
        """register -> catalog -> tool call must cost one SKILL.md request."""
        route = respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            registry = SkillRegistry()
            await registry.register("test-skill", provider)
            await registry.get_skills_catalog()
            await registry.get_skill("test-skill").get_body()
            await registry.get_skill("test-skill").get_metadata()

        assert route.call_count == 1

    @respx.mock
    async def test_resource_fetches_are_not_cached(self):
        """Only SKILL.md is cached; resources are fetched on demand."""
        respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        route = respx.get(f"{BASE}/test-skill/scripts/run.sh").respond(content=b"echo hi")
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            await provider.get_script("test-skill", "run.sh")
            await provider.get_script("test-skill", "run.sh")

        assert route.call_count == 2

    @respx.mock
    async def test_cache_is_per_instance(self):
        route = respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        async with HTTPStaticFileSkillProvider(BASE) as first:
            await first.get_body("test-skill")
        async with HTTPStaticFileSkillProvider(BASE) as second:
            await second.get_body("test-skill")

        assert route.call_count == 2

    @respx.mock
    async def test_invalidate_refetches(self):
        route = respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            await provider.get_body("test-skill")
            provider.invalidate("test-skill")
            await provider.get_body("test-skill")
            provider.invalidate()
            await provider.get_body("test-skill")

        assert route.call_count == 3

    @respx.mock
    async def test_revalidate_sends_validators_and_honours_304(self):
        """With revalidate=True the provider re-checks but reuses the body."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.headers.get("if-none-match") == '"v1"':
                return httpx.Response(304)
            return httpx.Response(200, text=SKILL_MD, headers={"ETag": '"v1"'})

        respx.get(f"{BASE}/test-skill/SKILL.md").mock(side_effect=handler)

        async with HTTPStaticFileSkillProvider(BASE, revalidate=True) as provider:
            first = await provider.get_body("test-skill")
            second = await provider.get_body("test-skill")

        assert first == second
        assert len(requests) == 2
        assert "if-none-match" not in requests[0].headers
        assert requests[1].headers["if-none-match"] == '"v1"'

    @respx.mock
    async def test_revalidate_picks_up_new_content(self):
        """A 200 during revalidation replaces the cached body."""
        responses = [
            httpx.Response(200, text=SKILL_MD, headers={"ETag": '"v1"'}),
            httpx.Response(
                200,
                text=SKILL_MD.replace("body of the test skill", "updated body"),
                headers={"ETag": '"v2"'},
            ),
            httpx.Response(304),
        ]
        route = respx.get(f"{BASE}/test-skill/SKILL.md").mock(side_effect=responses)

        async with HTTPStaticFileSkillProvider(BASE, revalidate=True) as provider:
            assert "updated body" not in await provider.get_body("test-skill")
            assert "updated body" in await provider.get_body("test-skill")
            assert "updated body" in await provider.get_body("test-skill")

        assert route.calls[2].request.headers["if-none-match"] == '"v2"'


class TestResourceListing:
    """Listing requires an opt-in ``index.json`` manifest."""

    def test_capability_off_by_default(self):
        provider = HTTPStaticFileSkillProvider(BASE)
        assert provider.supports_resource_listing is False

    def test_capability_on_when_manifest_declared(self):
        provider = HTTPStaticFileSkillProvider(BASE, resource_manifest=True)
        assert provider.supports_resource_listing is True

    @respx.mock
    async def test_raises_when_not_configured(self):
        """A plain static host must say 'cannot enumerate', not 'no resources'."""
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(ResourceListingNotSupportedError, match="resource_manifest"):
                await provider.list_resources("test-skill")
        assert not respx.calls

    @respx.mock
    async def test_reads_manifest(self):
        respx.get(f"{BASE}/test-skill/index.json").respond(
            json={
                "references": ["sev.md", "esc.md"],
                "scripts": ["run.sh"],
                "assets": ["diagram.mermaid"],
            }
        )
        async with HTTPStaticFileSkillProvider(BASE, resource_manifest=True) as provider:
            assert await provider.list_resources("test-skill") == {
                "references": ["esc.md", "sev.md"],
                "scripts": ["run.sh"],
                "assets": ["diagram.mermaid"],
            }

    @respx.mock
    async def test_missing_kinds_default_to_empty(self):
        respx.get(f"{BASE}/test-skill/index.json").respond(json={"scripts": ["run.sh"]})
        async with HTTPStaticFileSkillProvider(BASE, resource_manifest=True) as provider:
            assert await provider.list_resources("test-skill") == {
                "references": [],
                "scripts": ["run.sh"],
                "assets": [],
            }

    @respx.mock
    async def test_unsafe_names_are_dropped(self):
        """A manifest is host data and its names are interpolated into URLs."""
        respx.get(f"{BASE}/test-skill/index.json").respond(
            json={"references": ["ok.md", "../../etc/passwd", "a/b.md", "", 42]}
        )
        async with HTTPStaticFileSkillProvider(BASE, resource_manifest=True) as provider:
            listing = await provider.list_resources("test-skill")
        assert listing["references"] == ["ok.md"]

    @respx.mock
    async def test_absent_manifest_reports_unsupported(self):
        # The skill is there; only its manifest is missing.
        respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        respx.get(f"{BASE}/test-skill/index.json").respond(404)
        async with HTTPStaticFileSkillProvider(BASE, resource_manifest=True) as provider:
            with pytest.raises(ResourceListingNotSupportedError, match=r"No index\.json"):
                await provider.list_resources("test-skill")

    @respx.mock
    async def test_absent_skill_is_not_reported_as_a_missing_manifest(self):
        """A 404 on the manifest means one of two things, and they differ."""
        respx.get(f"{BASE}/ghost/SKILL.md").respond(404)
        respx.get(f"{BASE}/ghost/index.json").respond(404)
        async with HTTPStaticFileSkillProvider(BASE, resource_manifest=True) as provider:
            with pytest.raises(SkillNotFoundError):
                await provider.list_resources("ghost")

    @respx.mock
    async def test_invalid_json_raises(self):
        respx.get(f"{BASE}/test-skill/index.json").respond(content=b"not json")
        async with HTTPStaticFileSkillProvider(BASE, resource_manifest=True) as provider:
            with pytest.raises(AgentSkillsError, match="not valid JSON"):
                await provider.list_resources("test-skill")

    @respx.mock
    async def test_non_object_manifest_raises(self):
        respx.get(f"{BASE}/test-skill/index.json").respond(json=["sev.md"])
        async with HTTPStaticFileSkillProvider(BASE, resource_manifest=True) as provider:
            with pytest.raises(AgentSkillsError, match="must be a JSON object"):
                await provider.list_resources("test-skill")

    @respx.mock
    async def test_non_list_kind_raises(self):
        respx.get(f"{BASE}/test-skill/index.json").respond(json={"scripts": "run.sh"})
        async with HTTPStaticFileSkillProvider(BASE, resource_manifest=True) as provider:
            with pytest.raises(AgentSkillsError, match="non-list"):
                await provider.list_resources("test-skill")

    @respx.mock
    async def test_traversal_in_skill_id_rejected(self):
        async with HTTPStaticFileSkillProvider(BASE, resource_manifest=True) as provider:
            with pytest.raises(SkillNotFoundError):
                await provider.list_resources("../secrets")
        assert not respx.calls


class TestSkillDiscovery:
    """``discover()`` against the root ``index.json``."""

    def test_capability_off_by_default(self):
        assert HTTPStaticFileSkillProvider(BASE).supports_discovery is False

    def test_capability_on_when_manifest_declared(self):
        assert HTTPStaticFileSkillProvider(BASE, skill_manifest=True).supports_discovery is True

    @respx.mock
    async def test_raises_when_not_configured(self):
        """A plain static host must say 'cannot enumerate', not 'no skills'."""
        async with HTTPStaticFileSkillProvider(BASE) as provider:
            with pytest.raises(DiscoveryNotSupportedError, match="skill_manifest"):
                await provider.discover()
        assert not respx.calls

    @respx.mock
    async def test_reads_manifest(self):
        respx.get(f"{BASE}/index.json").respond(json={"skills": ["b-skill", "a-skill"]})
        async with HTTPStaticFileSkillProvider(BASE, skill_manifest=True) as provider:
            assert await provider.discover() == ["a-skill", "b-skill"]

    @respx.mock
    async def test_missing_key_means_no_skills(self):
        respx.get(f"{BASE}/index.json").respond(json={"references": ["sev.md"]})
        async with HTTPStaticFileSkillProvider(BASE, skill_manifest=True) as provider:
            assert await provider.discover() == []

    @respx.mock
    async def test_unsafe_and_duplicate_ids_are_dropped(self):
        """A manifest is host data and its IDs are interpolated into URLs."""
        respx.get(f"{BASE}/index.json").respond(
            json={"skills": ["ok", "../../etc/passwd", "a/b", "", 42, "ok"]}
        )
        async with HTTPStaticFileSkillProvider(BASE, skill_manifest=True) as provider:
            assert await provider.discover() == ["ok"]

    @respx.mock
    async def test_absent_manifest_reports_unsupported(self):
        respx.get(f"{BASE}/index.json").respond(404)
        async with HTTPStaticFileSkillProvider(BASE, skill_manifest=True) as provider:
            with pytest.raises(DiscoveryNotSupportedError, match=r"No index\.json"):
                await provider.discover()

    @respx.mock
    async def test_invalid_json_raises(self):
        respx.get(f"{BASE}/index.json").respond(content=b"not json")
        async with HTTPStaticFileSkillProvider(BASE, skill_manifest=True) as provider:
            with pytest.raises(AgentSkillsError, match="not valid JSON"):
                await provider.discover()

    @respx.mock
    async def test_non_object_manifest_raises(self):
        respx.get(f"{BASE}/index.json").respond(json=["a-skill"])
        async with HTTPStaticFileSkillProvider(BASE, skill_manifest=True) as provider:
            with pytest.raises(AgentSkillsError, match="must be a JSON object"):
                await provider.discover()

    @respx.mock
    async def test_non_list_skills_raises(self):
        respx.get(f"{BASE}/index.json").respond(json={"skills": "a-skill"})
        async with HTTPStaticFileSkillProvider(BASE, skill_manifest=True) as provider:
            with pytest.raises(AgentSkillsError, match="non-list"):
                await provider.discover()

    @respx.mock
    async def test_registers_a_whole_host(self):
        respx.get(f"{BASE}/index.json").respond(json={"skills": ["test-skill"]})
        respx.get(f"{BASE}/test-skill/SKILL.md").respond(text=SKILL_MD)
        registry = SkillRegistry()
        async with HTTPStaticFileSkillProvider(BASE, skill_manifest=True) as provider:
            assert await registry.register_all(provider) == ["test-skill"]
        assert [skill.get_id() for skill in registry.list_skills()] == ["test-skill"]
