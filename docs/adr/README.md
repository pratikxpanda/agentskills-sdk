# Architecture decision records

ADRs capture cross-package decisions that are expensive to re-litigate.
Use them for architecture choices that constrain providers, integrations,
release process, or public behavior.

## Numbering and file names

- Number sequentially: `0001`, `0002`, `0003`, ...
- Use a short slug: `docs/adr/0009-meaningful-slug.md`
- Never renumber existing ADRs

## Status values

- `Accepted` for current decisions
- `Superseded by ADR XXXX` when replaced
- `Proposed` for an in-flight decision

## Template

```md
# ADR XXXX — Short title

**Status:** Accepted
**Date:** YYYY-MM
**Packages:** `agentskills-core`, `agentskills-fs`

## Context

What changed, what constraints matter, and why this needed a decision.

## Decision

What we chose and the concrete rule.

## Consequences

**Good**

- Benefits and why this is worth the trade.

**Costs**

- Ongoing costs, coupling, or limitations.

## Alternatives considered

- Rejected option and why.

## Decision history

- Link to the issue or PR where the decision was made.
```

## Index

- [ADR 0001](0001-mcp-context-provider-packaging.md) — MCP context provider packaging
- [ADR 0002](0002-optional-provider-capabilities.md) — Optional provider capabilities
- [ADR 0003](0003-fully-async-provider-interface.md) — Fully async provider interface
- [ADR 0004](0004-multi-package-lockstep-versioning.md) — Multi-package lockstep versioning
- [ADR 0005](0005-provider-caching-and-invalidation.md) — Provider caching and invalidation
- [ADR 0006](0006-exception-taxonomy-not-found-vs-unavailable.md) — Exception taxonomy
- [ADR 0007](0007-binary-resource-json-envelope.md) — Binary resource envelope
- [ADR 0008](0008-logging-namespace-and-severity.md) — Logging conventions
- [ADR 0009](0009-native-image-content.md) — Native image content, opt-in
