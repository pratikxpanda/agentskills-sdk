# ADR 0003 — Provider interface stays fully async

**Status:** Accepted
**Date:** 2026-08
**Packages:** `agentskills-core`, `agentskills-fs`, `agentskills-http`, integrations

## Context

`SkillProvider` is consumed from async call sites (MCP server, integrations,
registry operations), but filesystem work originally used sync I/O under async
methods in the local provider. That blocked the event loop and constrained
concurrency in long-running processes.

A forked model with both sync and async provider APIs was considered
unnecessary complexity for a codebase already standardized on asyncio.

## Decision

The provider contract remains fully async.

- Public provider operations are async methods.
- Blocking I/O in providers is moved to worker threads.
- No parallel sync provider interface is introduced.

## Consequences

**Good**

- One concurrency model across core, providers, and integrations.
- Event-loop safety is enforced at provider boundaries.
- Call sites do not need sync/async adapter branches.

**Costs**

- Provider implementors must reason about thread handoff for blocking I/O.
- Contributors can accidentally reintroduce blocking paths without tests.

## Alternatives considered

- Add a sync provider interface and adapters: rejected as duplicate API
  surface and behavioral drift risk.
- Keep sync-under-async reads: rejected for event-loop blocking and poor
  server concurrency.

## Decision history

- [v0.3 issue 3: Stop blocking the event loop in the filesystem provider](../issues/v0.3.md#3-stop-blocking-the-event-loop-in-the-filesystem-provider)
