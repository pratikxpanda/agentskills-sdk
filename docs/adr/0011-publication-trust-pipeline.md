# ADR 0011 — Publication pipeline: verify, transform, then refresh atomically

**Status:** Accepted
**Date:** 2026-10
**Packages:** `agentskills-core`, `agentskills-http`, `agentskills-mcp-server`

## Context

Manifest digests come from the same server as the content, so they prove consistency and
nothing else. v0.7 needed publisher verification, content policy, refresh, and an
outage story, and each interacts with the others. A policy that rewrites a file changes
its digest. A refresh that swaps files one at a time can show a manifest that disagrees
with the bytes. A stale fallback can quietly serve content a newer capture rejected.

## Decision

Publication is a fixed pipeline over an immutable snapshot, and a catalog is replaced as a unit.

1. **Capture** a bounded snapshot of every file.
2. **Verify** a detached Ed25519 signature over origin, skill ID, version, and a revision
   covering every path and byte. Keys come from trusted configuration, never from the
   skill. A supplied invalid proof is rejected even when unsigned content is allowed.
3. **Transform** with trusted hooks and an explicit token limit, then build the manifest
   from the delivered bytes. The source evidence is kept beside the delivered revision.
4. **Swap** the whole staged catalog atomically. Each catalog serves one audience.
5. **Stale serving** is off by default. With `max_stale_age` it may cover only a
   `ProviderUnavailableError`, re-runs verification and policy, and is refused after any
   observed change, removal, revoked key, or unsigned source.

Outbound HTTP validates and pins DNS answers per connection and allows only public
addresses unless `allow_private_network=True`. Telemetry is content-free by construction.

## Consequences

### Good

- A host can tell unsigned, verified, and transformed content apart.
- A reader never sees a half-applied refresh or a snapshot an outage resurrected unsafely.

### Costs

- The payload is an SDK contract, not an MCP standard, so hosts must opt in to check it.
- `cryptography` and OpenTelemetry are optional extras of core.
- Refresh and health are programmatic. The CLI captures once and has no scheduler.
- Callers own audience routing and key distribution.

## Alternatives considered

- Sigstore identities first: deferred because it adds a service dependency. The payload
  does not preclude it.
- Put signatures inside the skill folder: rejected because the signature would have to
  cover itself.
- Serve stale content after any error: rejected because it would mask removal and revocation.
- Allow private networks by default: rejected because an SSRF default is hard to retract.

## Decision history

- [Trust and Operability guide](../trust-and-operability.md) and the roadmap v0.7 section.
