---
title: MCP Skills Server
description: Native MCP Skills delivery and the async server factory.
---

Serves the official Skills extension on MCP SDK 2.2+ and protocol 2026-07-28.
See the [migration guide](../mcp-migration.md) and
[server setup](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/integrations/agentskills-mcp-server/README.md).

```bash
pip install "agentskills-mcp-server[fs]>=0.7,<0.8"
```

The command above applies once v0.7 is published. Until then, install the checkout.

::: agentskills_mcp_server.native.create_mcp_server
    options:
      show_root_heading: true

## Server

::: agentskills_mcp_server.native.NativeSkillsServer
    options:
      show_root_heading: true

## Configuration

::: agentskills_mcp_server.config.ServerConfig
    options:
      show_root_heading: true

::: agentskills_mcp_server.config.TrustConfig
    options:
      show_root_heading: true
