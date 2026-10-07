---
title: Examples
description: Native MCP Skills publication and model-free discovery benchmarks.
---

## Native Publication

Run from the repository root after installing the development checkout:

```bash
python -m agentskills_mcp_server --config examples/server-fs.json --check
python -m agentskills_mcp_server --config examples/server-fs.json
```

The sample uses the `incident-response` skill under `examples/skills/`. The tools
CLI also supports `agentskills serve examples/skills --check` and
`agentskills serve examples/skills` without a configuration file.

The HTTP configuration requires a static host serving complete per-skill file
manifests. Point its `base_url` at that host. A plain file server without those
manifests cannot publish native Skills.

## Native Discovery and Reads

```bash
python examples/mcp/benchmark.py --sizes 1 10 100 --repeats 3
```

The [benchmark guide](../docs/mcp-benchmarks.md) describes the corpus, requests,
digest verification, and limitations. No model credentials are needed. Native
stdio and loopback HTTP tests also exercise real protocol round trips.

## Retired Framework Examples

The LangChain, Agent Framework, and legacy MCP examples are preserved in the
[v0.6.0 tag](https://github.com/pratikxpanda/agentskills-sdk/tree/v0.6.0/examples).
They depend on removed APIs and are not v0.7 recipes. Read the
[migration guide](../docs/mcp-migration.md) before upgrading.

An ordinary MCP tool client is not a native Skills host. Selection, approval,
digest verification, context injection, and execution policy remain host-owned.