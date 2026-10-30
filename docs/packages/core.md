---
title: Core
description: Provider contracts, skill registration, validation, snapshots, and publication controls.
---

Registry, provider contract, validation, and shared exceptions.

```bash
pip install agentskills-core
pip install "agentskills-core[verification]"   # Ed25519 signature verification
pip install "agentskills-core[telemetry]"      # OpenTelemetry export
```

Core is storage-agnostic. Install a provider separately to read files or remote sources. Start
with the [runnable filesystem-backed example](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/core/agentskills-core/README.md#quick-start)
before using the APIs below. Registration reads and validates skill metadata and bodies. It
does not inject prompts or start an MCP server.

::: agentskills_core
    options:
      show_root_heading: true

## Publisher verification

See [Trust and Operability](../trust-and-operability.md) for the contract.

::: agentskills_core.trust
    options:
      show_root_heading: true

## Content policy

::: agentskills_core.policy
    options:
      show_root_heading: true

## Refresh and stale serving

::: agentskills_core.refresh
    options:
      show_root_heading: true

## Telemetry

::: agentskills_core.telemetry
    options:
      show_root_heading: true
