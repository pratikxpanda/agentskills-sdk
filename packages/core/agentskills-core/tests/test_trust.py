"""Publisher verification and approval identity regression tests."""

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentskills_core.snapshots import SkillFile, SkillSnapshot
from agentskills_core.trust import (
    DetachedSignature,
    TrustPolicy,
    VerificationError,
    content_revision,
    signature_payload,
)


@pytest.fixture
def snapshot():
    return SkillSnapshot(
        "alpha",
        (
            SkillFile(
                "SKILL.md", b"---\nname: alpha\ndescription: Test\nversion: '1.0.0'\n---\nBody"
            ),
            SkillFile("assets/data.bin", b"\x00\xff"),
        ),
    )


@pytest.fixture
def signed(snapshot):
    key = Ed25519PrivateKey.generate()
    policy = TrustPolicy("publisher:alpha", {"release": key.public_key().public_bytes_raw()})
    proof = DetachedSignature(
        "release", key.sign(signature_payload(snapshot, origin=policy.origin))
    )
    return policy, proof


def test_given_valid_signature_when_verified_then_identity_is_content_bound(snapshot, signed):
    policy, proof = signed

    result = policy.verify(snapshot, proof)

    assert (result.status, result.publisher, result.revision) == (
        "verified",
        "release",
        content_revision(snapshot),
    )


@pytest.mark.parametrize("change", ["bytes", "path", "added", "removed", "id", "version"])
def test_given_tampered_snapshot_when_verified_then_rejected(snapshot, signed, change):
    policy, proof = signed
    files = list(snapshot.files)
    if change == "bytes":
        files[1] = SkillFile(files[1].path, b"different")
    elif change == "path":
        files[1] = SkillFile("other.bin", files[1].data)
    elif change == "added":
        files.append(SkillFile("extra.txt", b"extra"))
    elif change == "removed":
        files.pop()
    elif change == "version":
        files[0] = SkillFile("SKILL.md", files[0].data.replace(b"1.0.0", b"2.0.0"))
    changed = SkillSnapshot("other" if change == "id" else "alpha", tuple(files))

    with pytest.raises(VerificationError):
        policy.verify(changed, proof)


@pytest.mark.parametrize(
    "options",
    [
        {"origin": "other"},
        {"version": "2.0.0"},
        {"revision": "sha256:wrong"},
        {"trusted_keys": {}},
        {"trusted_keys": {"release": b"bad-key"}},
    ],
)
def test_given_wrong_trust_context_when_verified_then_rejected(snapshot, signed, options):
    policy, proof = signed

    with pytest.raises(VerificationError):
        replace(policy, **options).verify(snapshot, proof)


def test_given_unsigned_content_when_policy_requires_signature_then_rejected(snapshot, signed):
    policy, _ = signed

    with pytest.raises(VerificationError, match="required"):
        policy.verify(snapshot)


def test_given_unsigned_allowed_when_proof_is_invalid_then_no_downgrade(snapshot, signed):
    policy, proof = signed
    unsigned = replace(policy, require_signature=False)

    assert unsigned.verify(snapshot).status == "unsigned"
    with pytest.raises(VerificationError):
        unsigned.verify(snapshot, replace(proof, signature=b"invalid"))


def test_given_reordered_files_when_verified_then_identity_is_unchanged(snapshot, signed):
    policy, proof = signed

    assert policy.verify(replace(snapshot, files=tuple(reversed(snapshot.files))), proof) == (
        policy.verify(snapshot, proof)
    )


def test_given_matching_pins_when_verified_then_accepted(snapshot, signed):
    policy, proof = signed

    assert (
        replace(policy, version="1.0.0", revision=content_revision(snapshot))
        .verify(snapshot, proof)
        .status
        == "verified"
    )


@pytest.mark.parametrize("origin", ["", "x" * 513, "bad\norigin"])
def test_given_invalid_origin_when_signed_then_rejected(snapshot, origin):
    with pytest.raises(ValueError):
        signature_payload(snapshot, origin=origin)


def test_given_non_string_version_when_signed_then_rejected(snapshot):
    changed = replace(
        snapshot, files=(SkillFile("SKILL.md", snapshot.files[0].data.replace(b"'1.0.0'", b"1.0")),)
    )

    with pytest.raises(VerificationError, match="version"):
        signature_payload(changed, origin="test")


def test_given_missing_crypto_when_verified_then_actionable_error(snapshot, signed, monkeypatch):
    policy, proof = signed
    monkeypatch.setitem(__import__("sys").modules, "cryptography.exceptions", None)

    with pytest.raises(ImportError, match="verification"):
        policy.verify(snapshot, proof)
