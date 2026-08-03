"""The HTTP provider, run against the shared conformance suite.

Nothing here is specific to HTTP beyond wiring up the routes: the
assertions are the ones every provider shares.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import respx

from agentskills_http import HTTPStaticFileSkillProvider
from agentskills_testing import (
    ASSET_BYTES,
    ASSET_NAME,
    REFERENCE_BYTES,
    REFERENCE_NAME,
    SCRIPT_BYTES,
    SCRIPT_NAME,
    SKILL_ID,
    ContentLimitConformanceSuite,
    ProviderConformanceSuite,
    build_skill,
    render_skill_md,
)

BASE = "https://skills.example.com"

_RESOURCES = (
    ("references", REFERENCE_NAME, REFERENCE_BYTES),
    ("scripts", SCRIPT_NAME, SCRIPT_BYTES),
    ("assets", ASSET_NAME, ASSET_BYTES),
)


def _serve_contract_skill(mock: respx.MockRouter) -> None:
    """Route the conformance fixture contract, and 404 everything else."""
    mock.get(f"{BASE}/{SKILL_ID}/SKILL.md").respond(text=render_skill_md(build_skill(SKILL_ID)))
    for kind, name, data in _RESOURCES:
        mock.get(f"{BASE}/{SKILL_ID}/{kind}/{name}").respond(content=data)


@pytest.fixture
def contract_host() -> Iterator[None]:
    """Serve the conformance fixture contract over mocked HTTP.

    Every route not listed here 404s, which is what the suite's
    unknown-skill and unknown-resource assertions rely on.
    """
    with respx.mock(assert_all_called=False) as mock:
        _serve_contract_skill(mock)
        mock.route().mock(return_value=httpx.Response(404))
        yield


@pytest.fixture
def contract_host_with_manifests() -> Iterator[None]:
    """The same host, publishing both ``index.json`` manifests."""
    with respx.mock(assert_all_called=False) as mock:
        _serve_contract_skill(mock)
        mock.get(f"{BASE}/index.json").respond(json={"skills": [SKILL_ID]})
        mock.get(f"{BASE}/{SKILL_ID}/index.json").respond(
            text=json.dumps({kind: [name] for kind, name, _ in _RESOURCES})
        )
        mock.route().mock(return_value=httpx.Response(404))
        yield


@pytest.fixture(scope="module")
def client() -> httpx.AsyncClient:
    """One client for the whole module.

    Building an ``AsyncClient`` costs a TLS context, and the suite runs
    fifty tests. respx intercepts before the client touches a socket, so
    it never binds to an event loop and is safe to share.
    """
    return httpx.AsyncClient()


@pytest.mark.usefixtures("contract_host")
class TestHTTPStaticFileConformance(ProviderConformanceSuite):
    @pytest.fixture
    def provider(self, client: httpx.AsyncClient) -> HTTPStaticFileSkillProvider:
        # Without manifests a static host cannot be enumerated, so the
        # suite takes the not-supported branch for both capabilities.
        return HTTPStaticFileSkillProvider(BASE, client=client)


@pytest.mark.usefixtures("contract_host_with_manifests")
class TestHTTPStaticFileManifestConformance(ProviderConformanceSuite):
    @pytest.fixture
    def provider(self, client: httpx.AsyncClient) -> HTTPStaticFileSkillProvider:
        # The same assertions again with both optional capabilities on,
        # which is the only way the manifest branches get contract-tested.
        return HTTPStaticFileSkillProvider(
            BASE, client=client, resource_manifest=True, skill_manifest=True
        )


@pytest.mark.usefixtures("contract_host")
class TestHTTPStaticFileContentLimits(ContentLimitConformanceSuite):
    @pytest.fixture
    def limited_provider(self, client: httpx.AsyncClient) -> HTTPStaticFileSkillProvider:
        return HTTPStaticFileSkillProvider(BASE, client=client, max_response_bytes=4)
