# ADR 0008 — One agentskills logging namespace with intentional severity

**Status:** Accepted
**Date:** 2026-08
**Packages:** all

## Context

Logs were inconsistent across distributions because module names reflected
package import paths (`agentskills_http.*`, `agentskills_core.*`), which broke a
single logger hierarchy and made operator-level filtering unreliable.

Severity conventions also needed explicit rules to avoid duplicate or noisy
error reporting between raising code and catching boundaries.

## Decision

Use one `agentskills.*` logger namespace and keep severity semantics narrow.

- Logger names are rewritten to one shared `agentskills.*` hierarchy.
- `WARNING` signals dropped/degraded behavior that execution can continue from.
- `ERROR` is not used in libraries that are about to raise.
- Exception boundaries decide final severity where needed.

## Consequences

**Good**

- One logger root can control verbosity across all packages.
- Logs align better with operational decision points.
- Duplicate "logged and raised" error events are reduced.

**Costs**

- Contributors must follow conventions rather than default habits.
- Misuse can creep back without review discipline.

## Alternatives considered

- Keep distribution-native logger names: rejected for fragmented control.
- Log errors at every raise site: rejected because it duplicates events and
  preempts caller severity decisions.

## Decision history

- [v0.3 issue 8: Structured logging across the SDK](../issues/v0.3.md#8-structured-logging-across-the-sdk)
