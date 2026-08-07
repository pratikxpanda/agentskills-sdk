# ADR 0007 — Binary resources use a JSON envelope

**Status:** Accepted
**Date:** 2026-08
**Packages:** `agentskills-core`, all integrations

## Context

Resource APIs return text. Binary content needs transport across multiple
integrations with consistent behavior and without silent corruption.

MCP has native binary content blocks, but other integrations and existing
consumers expected one uniform shape from `encode_resource_content()`.

## Decision

Binary resources are encoded as a JSON envelope with media type and base64
payload.

- UTF-8 text remains plain text.
- Non-text bytes are encoded in a JSON object.
- The envelope is the cross-integration contract for now.

## Consequences

**Good**

- One representation across integrations.
- No lossy decode attempts for binary content.
- Callers can branch on a stable envelope shape.

**Costs**

- Consumers must unwrap one extra layer.
- MCP-native binary features are not used directly yet.
- A future migration will need compatibility handling.

## Alternatives considered

- Return opaque bytes everywhere: rejected due to integration mismatch.
- Use MCP-native binary blocks only: rejected for inconsistent behavior across
  non-MCP integrations.

## Decision history

- [v0.3 issue 5: Return binary resources without corrupting bytes](../issues/v0.3.md#5-return-binary-resources-without-corrupting-bytes)
- [v0.4 follow-up note requesting a future reversal toward MCP-native blocks](../issues/v0.4.md#mcp-native-binary-content-blocks)
