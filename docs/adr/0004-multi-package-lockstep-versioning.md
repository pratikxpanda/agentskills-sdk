# ADR 0004 — Multi-package architecture with lockstep versions

**Status:** Accepted
**Date:** 2026-08
**Packages:** all

## Context

The SDK is split into focused distributions (core, providers, integrations,
CLI, testing) rather than one package with optional extras. This shapes install
UX and keeps framework/provider dependencies out of `agentskills-core`.

The cost is release coordination. Inter-package dependency floors can drift and
produce import-time failures if one distribution resolves an older sibling.

## Decision

Keep the multi-package architecture and enforce lockstep versioning.

- Each package is independently published.
- All packages share one release version per milestone.
- Dependents require the matching `agentskills-core` floor for that release.
- Release checks fail if versions or required floors drift.

## Consequences

**Good**

- Consumers install only what they need.
- Core stays dependency-light and reusable.
- Packaging boundaries match responsibility boundaries.

**Costs**

- Release process is more complex than a monolith.
- New packages must be wired into multiple scripts/workflows.
- Version/floor checks are mandatory to avoid skew.

## Alternatives considered

- One package with extras: rejected for dependency bloat and weaker isolation
  between concerns.
- Independent package versioning: rejected for current cadence and dependency
  coupling; lockstep keeps compatibility obvious before 1.0.

## Decision history

- [v0.3 issue 10: Automate PyPI publishing with Trusted Publishing](../issues/v0.3.md#10-automate-pypi-publishing-with-trusted-publishing)
- [v0.3 issue 10 implementation notes: floor drift and lockstep enforcement](../issues/v0.3.md#implementation-notes)
- [v0.4 issue 12: Simplify publish workflow](../issues/v0.4.md#12-simplify-the-publish-workflow-drop-the-testpypi-path)
