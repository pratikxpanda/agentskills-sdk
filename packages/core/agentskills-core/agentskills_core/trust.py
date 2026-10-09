"""Detached publisher verification over complete, immutable skill captures.

Sign ``signature_payload(snapshot, origin=...)`` outside the SDK and supply
the detached proof through trusted deployment configuration. Keys and proofs
are not inferred from skill frontmatter or from a server-supplied digest.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType
from typing import Literal

from agentskills_core.exceptions import AgentSkillsError
from agentskills_core.manifests import build_skill_manifest
from agentskills_core.snapshots import SkillSnapshot


class VerificationError(AgentSkillsError):
    """Content, publisher, or immutable pin verification failed closed."""


def content_revision(snapshot: SkillSnapshot) -> str:
    """Return a deterministic SHA-256 revision covering every path and byte.

    File enumeration order is insignificant. Invalid or incomplete native
    snapshots are rejected before a revision can be used for approval.
    """
    build_skill_manifest(snapshot)
    entries = [[file.path, file.size, file.digest] for file in snapshot.files]
    payload = json.dumps(sorted(entries), separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + sha256(payload.encode("ascii")).hexdigest()


def signature_payload(snapshot: SkillSnapshot, *, origin: str) -> bytes:
    """Return the versioned, domain-separated bytes for detached Ed25519 signing.

    Origin is a caller-assigned non-secret stable identity, not a display name
    supplied by an untrusted server. The payload is an SDK attestation contract,
    not an extension to SKILL.md or the MCP Skills wire format.
    """
    if not origin or len(origin) > 512 or any(ord(character) < 32 for character in origin):
        raise ValueError("origin must be a nonempty, bounded stable identity")
    version = build_skill_manifest(snapshot)["frontmatter"].get("version")
    if version is not None and not isinstance(version, str):
        raise VerificationError("Signed content version must be a string")
    return json.dumps(
        {
            "contract": "agentskills-snapshot-v1",
            "origin": origin,
            "skillId": snapshot.skill_id,
            "version": version,
            "revision": content_revision(snapshot),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


@dataclass(frozen=True, slots=True)
class DetachedSignature:
    """An Ed25519 signature and a key identifier resolved only from trusted keys."""

    key_id: str
    signature: bytes


@dataclass(frozen=True, slots=True)
class ContentIdentity:
    """Verification evidence, never an assertion that instructions are safe."""

    origin: str
    revision: str
    status: Literal["unsigned", "verified"]
    publisher: str | None = None


@dataclass(frozen=True, slots=True)
class TrustPolicy:
    """Verify configured publisher keys and optional exact content/version pins.

    Args:
        origin: Trusted stable identity for this source.
        trusted_keys: Key IDs mapped to raw 32-byte Ed25519 public keys.
        require_signature: Reject unsigned content by default.
        revision: Optional exact SHA-256 content revision.
        version: Optional exact frontmatter version, in addition to byte verification.
    """

    origin: str
    trusted_keys: Mapping[str, bytes] = field(default_factory=dict)
    require_signature: bool = True
    revision: str | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "trusted_keys", MappingProxyType(dict(self.trusted_keys)))

    def verify(
        self, snapshot: SkillSnapshot, proof: DetachedSignature | None = None
    ) -> ContentIdentity:
        """Verify bytes and identity, rejecting supplied invalid proofs even if unsigned is allowed.

        Raises:
            VerificationError: A signature, publisher, or pin is invalid.
            ImportError: Signature verification needs the core ``verification`` extra.
        """
        payload = signature_payload(snapshot, origin=self.origin)
        revision = content_revision(snapshot)
        metadata = build_skill_manifest(snapshot)["frontmatter"]
        if self.revision is not None and revision != self.revision:
            raise VerificationError("Content revision does not match the configured pin")
        if self.version is not None and metadata.get("version") != self.version:
            raise VerificationError("Content version does not match the configured pin")
        if proof is None:
            if self.require_signature:
                raise VerificationError("A trusted publisher signature is required")
            return ContentIdentity(self.origin, revision, "unsigned")
        public_key = self.trusted_keys.get(proof.key_id)
        if public_key is None:
            raise VerificationError("Publisher key is not trusted")
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError:
            raise ImportError(
                "Install agentskills-core[verification] for Ed25519 verification"
            ) from None
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(proof.signature, payload)
        except (InvalidSignature, ValueError, TypeError):
            raise VerificationError("Publisher signature verification failed") from None
        return ContentIdentity(self.origin, revision, "verified", proof.key_id)
