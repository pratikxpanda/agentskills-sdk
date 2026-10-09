"""Catalog refresh never publishes partial or unverified stale content."""

import asyncio
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentskills_core.exceptions import (
    AgentSkillsError,
    ProviderUnavailableError,
    SkillNotFoundError,
    SkillUnavailableError,
)
from agentskills_core.policy import publish_snapshot
from agentskills_core.refresh import SnapshotCatalog
from agentskills_core.snapshots import SkillFile, SkillSnapshot
from agentskills_core.trust import (
    DetachedSignature,
    TrustPolicy,
    VerificationError,
    signature_payload,
)


@pytest.fixture
def source():
    return SkillSnapshot(
        "alpha", (SkillFile("SKILL.md", b"---\nname: alpha\ndescription: Test\n---\nBody"),)
    )


@pytest.fixture
def setup(source):
    key = Ed25519PrivateKey.generate()
    policy = TrustPolicy("test", {"key": key.public_key().public_bytes_raw()})
    proof = DetachedSignature("key", key.sign(signature_payload(source, origin="test")))
    state = {"sources": [source], "error": None, "time": 0, "policy": policy}

    async def loader():
        if state["error"] is not None:
            raise state["error"]
        return state["sources"]

    catalog = SnapshotCatalog(
        loader,
        lambda snapshot: publish_snapshot(snapshot, trust=state["policy"], proof=proof),
        max_stale_age=10,
        clock=lambda: state["time"],
    )
    return catalog, state


async def test_given_outage_when_refreshing_then_verified_snapshot_is_bounded(setup):
    catalog, state = setup
    assert not catalog.ready
    first = await catalog.refresh()
    state.update(error=ProviderUnavailableError("outage"), time=5)

    stale = await catalog.refresh()

    assert stale.stale and stale.publications == first.publications
    state["time"] = 11
    assert not catalog.ready
    with pytest.raises(SkillUnavailableError):
        await catalog.refresh()


@pytest.mark.parametrize(
    "error",
    [
        VerificationError("invalid"),
        SkillNotFoundError("removed"),
        SkillUnavailableError("drift"),
        AgentSkillsError("403"),
    ],
)
async def test_given_non_outage_failure_when_refreshing_then_old_content_is_withdrawn(setup, error):
    catalog, state = setup
    await catalog.refresh()
    state["error"] = error

    with pytest.raises(type(error)):
        await catalog.refresh()

    assert not catalog.ready


async def test_given_revoked_key_during_outage_when_refreshing_then_no_stale_downgrade(setup):
    catalog, state = setup
    await catalog.refresh()
    state.update(error=ProviderUnavailableError("outage"), policy=TrustPolicy("test"))

    with pytest.raises(VerificationError):
        await catalog.refresh()
    assert not catalog.ready


async def test_given_removed_skill_when_refreshing_then_new_catalog_is_empty(setup):
    catalog, state = setup
    first = await catalog.refresh()
    state["sources"] = []

    second = await catalog.refresh()

    assert second.publications == () and second.generation != first.generation


@pytest.mark.parametrize(
    "options",
    [
        {"max_skills": 0},
        {"max_total_bytes": -1},
        {"max_stale_age": -1},
        {"max_stale_age": float("nan")},
    ],
)
def test_given_invalid_catalog_bounds_when_constructing_then_rejected(options):
    with pytest.raises(ValueError):
        SnapshotCatalog(None, None, **options)


async def test_given_unsigned_snapshot_when_outage_then_no_stale(source):
    failed = False

    async def loader():
        if failed:
            raise ProviderUnavailableError("outage")
        return [source]

    catalog = SnapshotCatalog(
        loader,
        lambda snapshot: publish_snapshot(
            snapshot, trust=TrustPolicy("test", require_signature=False)
        ),
        max_stale_age=10,
    )
    await catalog.refresh()
    failed = True

    with pytest.raises(VerificationError):
        await catalog.refresh()
    assert not catalog.ready


async def test_given_inflight_refresh_when_reading_then_previous_generation_is_complete(source):
    waiting = asyncio.Event()
    release = asyncio.Event()
    sources = [source]

    async def loader():
        if waiting.is_set():
            await release.wait()
        return sources

    catalog = SnapshotCatalog(
        loader,
        lambda snapshot: publish_snapshot(
            snapshot, trust=TrustPolicy("test", require_signature=False)
        ),
    )
    first = await catalog.refresh()
    waiting.set()
    sources = []
    task = asyncio.create_task(catalog.refresh())
    await asyncio.sleep(0)
    assert catalog.current is first
    release.set()
    assert (await task).publications == ()


@pytest.mark.parametrize("case", ["count", "duplicate", "source_bytes", "output_bytes", "identity"])
async def test_given_invalid_staged_catalog_when_refreshing_then_rejected(source, case):
    sources = [source, source] if case in {"count", "duplicate"} else [source]

    async def loader():
        return sources

    def policy(snapshot):
        result = publish_snapshot(snapshot, trust=TrustPolicy("test", require_signature=False))
        if case == "identity":
            return replace(result, snapshot=replace(snapshot, skill_id="other"))
        if case == "output_bytes":
            return replace(
                result,
                snapshot=replace(
                    snapshot, files=(SkillFile("SKILL.md", snapshot.files[0].data + b"extra"),)
                ),
            )
        return result

    catalog = SnapshotCatalog(
        loader,
        policy,
        max_skills=1 if case == "count" else 128,
        max_total_bytes=0 if case == "source_bytes" else source.total_bytes,
    )
    with pytest.raises(ValueError):
        await catalog.refresh()
    assert not catalog.ready


@pytest.mark.parametrize("case", ["disabled", "too_old", "changed_policy"])
async def test_given_ineligible_previous_snapshot_when_outage_then_rejected(setup, case):
    catalog, state = setup
    await catalog.refresh()
    if case == "disabled":
        catalog._max_stale_age = 0
    elif case == "too_old":
        state["time"] = 11
    else:
        previous_policy = catalog._policy
        catalog._policy = lambda source: replace(previous_policy(source), annotations=("changed",))
    state["error"] = ProviderUnavailableError("outage")
    with pytest.raises((VerificationError, ProviderUnavailableError)):
        await catalog.refresh()
    assert not catalog.ready


def test_given_mutable_file_data_when_constructing_snapshot_then_rejected():
    with pytest.raises(ValueError, match="immutable"):
        SkillFile("SKILL.md", bytearray(b"mutable"))
