---
title: "ADR 0012: Pre-1.0 Compatibility Policy"
description: Same-minor sibling dependencies and one released minor of deprecation for future removals.
---

## Status

Accepted by the maintainer on 2026-11-04 for the v0.9 development line.

## Context

The SDK publishes eleven packages in lockstep. A sibling floor with a `<1.0` ceiling allowed
an older dependent to resolve a future pre-1.0 minor despite that minor containing breaking
changes. The unified serving CLI also calls a helper in the MCP distribution, making compatible
package selection important even when callers use only the console.

The project needs predictable migration handling before a 1.0 API freeze. Keeping every retired
entry point indefinitely would create a different maintenance burden, so deprecation has a
defined release window rather than implying permanent compatibility.

## Decision

- Before 1.0, sibling requirements have the current release as a floor and the next minor as an
  exclusive ceiling. For 0.9.0 this is `>=0.9.0,<0.10.0`.
- The rule includes optional sibling dependencies when selected. The version bump scripts and
  release checker generate and verify the same range, including double-digit minor versions.
- Patch releases preserve their minor family's supported contracts. Changes to exported imports,
  documented submodules, provider capabilities, exception semantics, CLI/config, data schemas,
  and required test-fixture data need compatibility review.
- A future removal must follow at least one released minor carrying a deprecation notice and
  migration path. A deprecation introduced in 0.10 cannot be removed before 0.11 or in a 0.10 patch.
- The separately approved v0.9 removal of the `agentskills-mcp` console is an explicit transition
  decision. This policy does not add an alias or reopen retired framework integrations.
- A 1.0 API freeze and stable-API support commitments require separate approval and evidence.

## Consequences

Installers reject unverified mixed-minor combinations rather than failing later on import or
CLI invocation. Coordinated package releases and sibling floors remain mandatory. Consumers
upgrading to another minor must upgrade the SDK packages they use together.

Future incompatible changes require a warning strategy, regression coverage, release notes, and
documented migration steps. An accepted policy is not proof of third-party host compatibility or
production TLS, identity, or provider authorization.

## References

- [ADR 0004: Lockstep Versions](0004-multi-package-lockstep-versioning.md)
- [Compatibility and API Inventory](../compatibility.md)
- [v0.9 Acceptance Criteria](../issues/v0.9.md)
