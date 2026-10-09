# ADR 0006: Distinguish not found from unavailable

**Status:** Accepted
**Date:** 2026-08
**Packages:** `agentskills-core`, `agentskills-http`, `agentskills-mcp-server`

## Context

Callers need different behavior for "resource does not exist" versus
"backend is temporarily unavailable". Treating both as the same error either
causes pointless retries or suppresses fallback paths.

HTTP semantics made this concrete: `404`/`410` and `429`/`5xx` are different
operational states and should be surfaced differently in the SDK.

## Decision

Keep a split exception taxonomy.

- `SkillNotFoundError` indicates stable absence.
- `SkillUnavailableError` indicates transient/backend unavailability.
- `SkillUnavailableError.retry_after` is preserved when available.
- Integrations use the distinction to choose retry/fallback behavior.
- `ProviderUnavailableError` (v0.7) subclasses `SkillUnavailableError` and marks a
  genuine provider outage. It is the only failure that verified stale serving may
  cover. Drift, access denial, and removal stay on the base type or on
  `SkillNotFoundError`, so a stale snapshot is never served past a known change.

## Consequences

### Good

- Retry behavior can be correct by construction.
- Agents can surface meaningful next steps to users.
- Operational incidents are distinguishable from content errors.

### Costs

- Provider implementations must map backend failures carefully.
- More exception types increase contract surface area.

## Alternatives considered

- One generic provider failure type: rejected because it hides retry intent.
- Retry all failures: rejected because `404`/`410` are not recoverable by retry.

## Decision history

- [v0.3 issue 7: Distinguish "not found" from "unavailable" in the HTTP provider](../issues/v0.3.md#7-distinguish-not-found-from-unavailable-in-the-http-provider)
