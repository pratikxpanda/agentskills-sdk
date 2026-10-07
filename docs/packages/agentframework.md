---
title: Retired Agent Framework Integration
description: Retirement notice for agentskills-agentframework and the MCP context bridge.
---

`agentskills-agentframework` and `AgentSkillsMcpContextProvider` were deprecated in
v0.6 and are removed from v0.7 releases. The
[v0.6.0 source](https://github.com/pratikxpanda/agentskills-sdk/tree/v0.6.0/packages/integrations/agentskills-agentframework)
and existing wheels remain available, without future framework compatibility guarantees.

Read the [native-only migration guide](../mcp-migration.md). Automatic catalog
injection, caching, and session pruning are now host responsibilities, not bridge features.
