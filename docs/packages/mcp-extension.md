---
title: MCP Skills Extension
description: Native MCP Skills publication, consumption, and client-side composition.
---

Publishes and consumes the official Skills extension on MCP SDK 2.2+ and protocol 2026-07-28.
See the [migration guide](../mcp-migration.md) and
[server setup](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/integrations/agentskills-mcp-extension/README.md).

```bash
pip install "agentskills-mcp-extension[fs]"
```

::: agentskills_mcp_extension.native.create_mcp_server
    options:
      show_root_heading: true

## Server

::: agentskills_mcp_extension.native.NativeSkillsServer
    options:
      show_root_heading: true

## Client

The framework-neutral client helper uses a caller-owned MCP session. Listing returns origin-bound
references without reading resource bodies. Resource reads happen on demand and verify the
manifest digest.

::: agentskills_mcp_extension.client.McpSkillsClient
    options:
      show_root_heading: true

::: agentskills_mcp_extension.client.McpSkillReference
    options:
      show_root_heading: true

::: agentskills_mcp_extension.client.McpSkillIdentity
    options:
      show_root_heading: true

Combine clients from distinct origins with `McpSkillsCollection`. It preserves `(origin, URI)`
identity and delegates reads without serving a proxy endpoint.

::: agentskills_mcp_extension.client.McpSkillsCollection
    options:
      show_root_heading: true

Set `skill_prompt_shortcuts=True` on `create_mcp_server` to register the optional `use-skill`
prompt. It is user-invoked, resolves a canonical URI against the current catalog, and does not
grant tool permissions.

## Configuration

::: agentskills_mcp_extension.config.ServerConfig
    options:
      show_root_heading: true

::: agentskills_mcp_extension.config.TrustConfig
    options:
      show_root_heading: true
