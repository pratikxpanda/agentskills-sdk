# ADR 0005 — Provider caching is per instance with explicit invalidation

**Status:** Accepted
**Date:** 2026-08
**Packages:** `agentskills-fs`, `agentskills-http`

## Context

Repeated reads of `SKILL.md` were on the hot path for validation, catalog
construction, and tool calls. Without caching, HTTP providers paid redundant
network round-trips and local providers repeatedly parsed frontmatter.

Revalidation and correctness matter for mutable hosts, but unconditional
revalidation conflicts with the "single request across common flows" goal.

## Decision

Cache `SKILL.md` per provider instance and expose explicit invalidation.

- Caching key is `skill_id` on the provider instance.
- `invalidate(skill_id=None)` clears one entry or all.
- HTTP revalidation (`ETag`/`Last-Modified`) is opt-in via provider config.
- Only `SKILL.md` is cached; resources are fetched on demand.

## Consequences

**Good**

- Fast default path for common static-host workflows.
- Correctness for mutable hosts remains available explicitly.
- Caller-visible cache control is simple and predictable.

**Costs**

- Revalidation mode and default mode differ by round-trip behavior.
- Resource reads remain uncached by design.
- Cache lifetime is tied to provider lifetime.

## Alternatives considered

- Always revalidate: rejected because it defeats the one-fetch fast path.
- TTL-based cache: rejected as guesswork for content freshness.
- Cache resources too: rejected for unbounded memory growth and lower payoff.

## Decision history

- [v0.3 issue 1: Cache SKILL.md content in providers](../issues/v0.3.md#1-cache-skillmd-content-in-providers)
