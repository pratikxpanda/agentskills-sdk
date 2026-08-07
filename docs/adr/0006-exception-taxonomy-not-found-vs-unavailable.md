# ADR 0006 — Distinguish not found from unavailable

**Status:** Accepted
**Date:** 2026-08
**Packages:** `agentskills-core`, `agentskills-http`, integrations

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

## Consequences

**Good**

- Retry behavior can be correct by construction.
- Agents can surface meaningful next steps to users.
- Operational incidents are distinguishable from content errors.

**Costs**

- Provider implementations must map backend failures carefully.
- More exception types increase contract surface area.

## Alternatives considered

- One generic provider failure type: rejected because it hides retry intent.
- Retry all failures: rejected because `404`/`410` are not recoverable by retry.

## Decision history

- [v0.3 issue 7: Map HTTP errors to SDK exceptions with retry hints](../issues/v0.3.md#7-map-http-errors-to-sdk-exceptions-with-retry-hints)
