---
title: Trust and Operability
description: Publisher verification, content policy, network controls, refresh, and disclosure telemetry in v0.7.
---

## Scope

v0.7 adds opt-in publisher verification and publication policy to native Skills
delivery. Outbound HTTP network protection is enabled by default. These controls
are implemented in the development tree, not a production deployment certification.
The release remains unpublished.

Server-provided hashes establish byte consistency, not authorship. A verified
signature establishes that a configured key signed particular bytes for a particular
origin and skill ID. It does not establish that the instructions are safe.
The SDK does not execute scripts, grant tools, approve nested skills, or sandbox hosts.

## Publisher Verification

Install `agentskills-core[verification]` for Ed25519 verification through
`cryptography`. Core still imports without that extra. Install local checkout
paths while v0.7 is unreleased:

```bash
python -m pip install './packages/core/agentskills-core[verification,telemetry]' ./packages/providers/agentskills-fs ./packages/integrations/agentskills-mcp-server
```

Publisher tooling captures an immutable complete source and signs
`signature_payload(snapshot, origin=...)`. Deploy the detached signature and
public key through a trusted channel outside the skill folder. A signature inside
the captured file set would introduce a circular digest dependency.

```python
from agentskills_core.policy import publish_snapshot
from agentskills_core.trust import DetachedSignature, TrustPolicy

trust = TrustPolicy(
    origin="publisher:operations",
    trusted_keys={"release-key-2026": public_key_bytes},
    revision=approved_revision,
    version="1.0.0",
)
proof = DetachedSignature("release-key-2026", detached_signature_bytes)

def publication_policy(snapshot):
    return publish_snapshot(snapshot, trust=trust, proof=proof)
```

`public_key_bytes` is a raw 32-byte Ed25519 public key. The signature is raw
64-byte signature data. Signing keys stay in publisher-controlled tooling and
never belong in a server config. Configure one policy/proof per skill.

The signed UTF-8 payload is ASCII JSON with sorted keys and compact separators.
It contains `contract="agentskills-snapshot-v1"`, `origin`, `skillId`, `version`
(a string or null), and `revision`. The revision is `sha256:` followed by the
SHA-256 of ASCII compact JSON containing sorted `[path, byte_size, file_digest]`
entries for every captured file. Each `file_digest` uses `sha256:` and the
original bytes. File enumeration order does not affect identity. Renames, added
files, removed files, frontmatter changes, and binary changes do.

This is an SDK detached-attestation contract, not a new SKILL.md field or MCP
signature standard. Key identifiers are resolved only against configured keys.
Unknown keys, invalid signatures, origin mismatches, and pin mismatches fail closed.
Allowing unsigned sources requires `require_signature=False`. A supplied invalid
signature is still rejected. Native static captures are either `unsigned` or
`verified`, never labelled dynamic to bypass verification. Dynamic publication is
not supported by this server and is ineligible for verified stale fallback.

The native factory accepts `publication_policy`, `origin`, `observer`, and
`max_stale_age`. Without a publication policy, content is explicitly unsigned.
Use a stable, non-secret origin identity. The default `unconfigured` is not a
trust assertion and must not be used as a production approval identity.

Config-driven preflight supports a `trust` object on each skill:

```json
{
  "id": "incident-response",
  "provider": "fs",
  "options": {"root": "./skills"},
  "trust": {
    "origin": "publisher:operations",
    "trusted_keys": {"release-key-2026": "${SKILL_PUBLIC_KEY_BASE64}"},
    "key_id": "release-key-2026",
    "signature": "${SKILL_SIGNATURE_BASE64}",
    "require_signature": true,
    "version": "1.0.0"
  }
}
```

`revision` optionally pins exact content. When any skill config enables trust,
every skill needs an explicit trust policy. This prevents an omitted config from
silently admitting an unsigned source. `--check` verifies signatures without listening.

## Content Policy and Host Approval

`publish_snapshot` first verifies the source, then applies ordered trusted hooks
to every file, then validates the transformed complete snapshot and its manifest.
Each hook receives a `SkillFile` and returns a `ContentDecision` with optional
replacement bytes, rejection, and bounded annotation codes. Hooks are trusted
application code, not code loaded from a skill. Injection heuristics are advisory.

```python
from agentskills_core.policy import ContentDecision, publish_snapshot

def redact_example(file):
    return ContentDecision(
        data=file.data.replace(b"internal-example-token", b"[redacted]"),
        annotations=("example-redaction",),
    )

def publication_policy(snapshot):
    return publish_snapshot(
        snapshot,
        trust=trust,
        proof=proof,
        hooks=[redact_example],
        max_tokens=8000,
        count_tokens=token_counter,
    )
```

Choose `token_counter` explicitly for the host model. It must return a nonnegative
integer. All valid UTF-8 files count, including frontmatter and nested SKILL.md
files. Binary resources retain byte limits. No implicit tokenizer download or
heuristic decides a security limit.

Redaction changes the delivered revision. `Publication.source_identity` retains
the original evidence separately. Resource `_meta["io.agentskills/publication"]`
reports origin, delivered revision, source revision/status, publisher key ID,
transformed status, and annotation codes. Skill entries from `skills/list` and
`skills/get` carry only the fields the extension defines. This metadata is an
optional SDK annotation, not proof a client should trust without verifying its server.

Hosts must display originating server plus canonical URI, verify file bytes,
and bind approval to the delivered revision. Redaction, updates, nested skills,
or newly requested permissions require a host approval decision. A source
signature does not cover redacted bytes. Reading a resource is not activation.
The host owns context injection, `allowed-tools`, execution grants, and sandboxing.

## Network and Deployment Controls

The default HTTP provider resolves DNS at connection time, rejects non-public,
multicast, reserved, loopback, and link-local answers, and connects directly to
a validated numeric IP. TLS retains the original hostname for SNI and certificate
validation. Mixed public/private DNS answers fail closed. New connections repeat
validation. Environment proxies are not inherited. Redirects are rejected in all
provider modes so credentials cannot follow them to another origin.

Internal destinations require `allow_private_network=True`. Caller-supplied
HTTPX clients require this same explicit opt-out because their transports,
proxies, DNS behavior, and TLS configuration are caller-owned. The SDK still
disables redirects and enforces response byte limits. A custom client must apply
equivalent network controls when used with untrusted destination input.
Use `headers` or `params` for credentials, not userinfo or query strings in
`base_url`. Never use an inbound client bearer token as an upstream credential.

Timeouts, retries, per-response byte limits, and aggregate snapshot limits remain
bounded. `require_tls=True` rejects plain HTTP. Private access is not permission
to contact arbitrary internal services. Deployment egress restrictions provide
additional protection and are required for environments with custom transports.

For remote MCP HTTP, construct the native server with the MCP SDK's `AuthSettings`
and a deployment-owned `TokenVerifier`. Set `validate_token_resource=True` and
required scopes. Use:

```python
app = server.secure_http_app(
    allowed_hosts=["skills.example.com"],
    allowed_origins=["https://approved-host.example.com"],
)
```

The helper rejects missing authorization and wildcard allowlists. The MCP SDK
validates host and origin headers and bearer tokens. CLI Streamable HTTP and
the ordinary SDK app factory remain local/deployment primitives, not authenticated
remote recipes. Terminate TLS at the deployment, validate forwarded headers at
the trusted proxy, and route each authorization audience to its own server/catalog.
The SDK does not implement an identity provider or per-user catalog routing.

## Refresh, Readiness, and Stale Content

Programmatic servers expose `await server.refresh()` and `server.health()`.
Refresh captures fresh bytes and metadata for all current handles, verifies and
transforms every skill, validates publication overlap, then swaps one complete
generation. Readers see the previous complete generation while staging occurs.
Removed handles disappear on success. Previous pagination cursors become invalid.
Clients must restart discovery after refresh and verify all bytes against the
manifest they approved. Separate MCP requests are not a cross-request transaction.

Keep programmatic providers open until server shutdown if refresh is needed.
The config CLI captures once and closes provider clients. It does not create a
refresh scheduler. Applications own scheduling, authorization routing, and health
endpoints. `health()` checks local publication readiness, not TLS or host behavior.
Cache scope remains `private` and TTL remains zero. No catalog is shared across
audiences by the refresh store.

Stale serving is disabled by default. `max_stale_age` enables bounded-age reuse
only for `ProviderUnavailableError`, a subclass of `SkillUnavailableError` used
for genuine HTTP outages. Previous source signatures and current policies are
checked again. No fallback occurs for unsigned content, invalid signatures,
revoked keys, access denial, known removal, observed changed bytes, capture drift,
or changed policy output. An outage after an observed change also fails closed.
The bound is measured from successful capture, not the last retry. Expiry blocks
reads. Other failures withdraw the catalog until a successful refresh.

Stale status is exposed through health, catalog metadata, resource-read metadata,
and observer events. A stale revision never bypasses the host's approval rules.
The store is memory-only and does not claim durable offline availability.

## Telemetry

Pass an observer callable to the native factory or HTTP provider. Events report
discovery, lookup, fetch, verification, refresh, and cache activity, with status,
byte counts, duration, cache hits, hashed origin identity, and delivered revision
when known. Paths, bodies, headers, query strings, and exception messages are
excluded. Observer exceptions cannot change delivery outcomes. Use non-secret
origin labels even though the observer hashes them.

`OpenTelemetryObserver` from `agentskills_core.telemetry` exports spans plus
`agentskills.operations`, `agentskills.bytes`, and `agentskills.duration` metrics.
Install `agentskills-core[telemetry]` and configure the OpenTelemetry SDK and
exporter in your application. The library never configures global providers or
export destinations. Metrics omit origin and revision labels to bound cardinality.
Events measure server operations, not host activation or task success.

## Validation Boundaries

Regression tests cover real Ed25519 proofs, complete-file tampering, token limits,
redaction revisions, atomic replacement, expiry, key revocation, observed-change
outages, public/private DNS policy, real loopback transport, inbound authorization,
host/origin rejection, and content-free telemetry. CI retains cross-Python and
external mcpc checks. Production identity infrastructure, TLS gateways, egress
firewalls, and host approval UX require deployment-specific validation.
