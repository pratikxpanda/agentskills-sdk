# Core (`agentskills-core`)

Registry, provider contract, validation, and shared exceptions.

```bash
pip install agentskills-core
pip install "agentskills-core[verification]"   # Ed25519 signature verification
pip install "agentskills-core[telemetry]"      # OpenTelemetry export
```

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
