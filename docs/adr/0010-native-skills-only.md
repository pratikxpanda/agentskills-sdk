# ADR 0010 — Native Skills only, with no legacy compatibility mode

**Status:** Accepted
**Date:** 2026-10
**Packages:** `agentskills-mcp-server`, `agentskills-tools`, release tooling

## Context

v0.6 shipped the official MCP Skills extension beside a legacy server: eight tools,
`skills://` catalog resources, an Agent Framework bridge, and two framework packages
(`agentskills-langchain`, `agentskills-agentframework`). The legacy surface supported MCP
SDK 1.x and 2.x, so every change had to work on both, and the migration examples for
both frameworks depended on it.

The roadmap planned to keep the legacy server until the frameworks reached native Skills
parity. That gate was not met. Holding it open meant carrying two delivery paths, two
SDK ranges, and ten distributions indefinitely.

## Decision

v0.7 serves the official Skills extension only.

- Remove the two framework packages, the bridge and its extra, the legacy server,
  its tools and catalogs, and MCP 1.x support. The server requires `mcp>=2.2,<3`.
- Delete the source from the active tree. Do not keep an `archived/` directory.
  The `v0.6.0` tag, published wheels, and versioned docs preserve history.
- Keep one factory name, `create_mcp_server`, and no `mode` setting. Unknown config
  keys are rejected so a leftover `mode` fails loudly.
- Keep `agentskills-adapters`, the framework-neutral core, retrieval, and the CLI.

## Consequences

### Good

- One delivery path, one SDK range, and eight distributions to test and release.
- No ambiguity about which code is supported or scanned.

### Costs

- Applications without a native Skills host lose their framework paths. They must pin
  the v0.6 family in an isolated environment, with no continued maintenance.
- Framework behavior such as catalog injection, pruning, and the fast path is now a
  host responsibility. The migration guide lists each gap.

## Alternatives considered

- Keep legacy mode until framework parity: rejected because the parity gate had no end date.
- Move retired packages to `archived/`: rejected because an in-tree copy still looks
  vendorable and invites scanning, dependency, and support questions.
- Yank the v0.6 releases: rejected because existing users would break for no benefit.

## Decision history

- Roadmap section "Native-Only Delivery" and the [migration guide](../mcp-migration.md).
