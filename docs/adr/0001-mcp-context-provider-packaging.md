# ADR 0001 — MCP context provider lives in `agentskills-mcp-server` behind an extra

**Status:** Accepted
**Date:** 2026-02
**Packages:** `agentskills-mcp-server`, `agentskills-agentframework`

## Context

There are two ways to connect a Microsoft Agent Framework agent to skills:

- **In-process** — `AgentSkillsContextProvider(registry)` in `agentskills-agentframework`, wrapping a `SkillRegistry` directly.
- **Out-of-process** — `agentskills-mcp-server` exposes skills as MCP tools and resources over stdio or HTTP.

The MCP path required manual wiring: connect via one of Agent Framework's MCP tool classes, read the catalog resources, assemble the system prompt, pass the tools. Agent Framework's MCP tool classes register the tools automatically but do nothing about instructions, so the catalog had to be injected by hand on every agent.

We needed a bridge, and had to decide where it lived. `agentskills-mcp-server` is deliberately framework-agnostic — it serves LangChain, custom agents, CLI clients, and anything else that speaks MCP. Adding a hard `agent-framework` dependency to it was not acceptable.

## Decision

`AgentSkillsMcpContextProvider` ships **inside `agentskills-mcp-server`, behind an optional `[agentframework]` extra**, rather than in `agentskills-agentframework` or a separate package.

| Layer | Install | Role |
| --- | --- | --- |
| MCP server (core) | `agentskills-mcp-server` | Universal protocol layer, framework-agnostic |
| MCP + AF adapter | `agentskills-mcp-server[agentframework]` | Adds the context provider, pulls in `agent-framework` |
| In-process provider | `agentskills-agentframework` | Wraps a `SkillRegistry` directly |

The adapter injects **instructions only**. It reads `skills://catalog/{format}` and `skills://tools-usage-instructions` from the MCP session and calls `context.extend_instructions()`.

It deliberately does **not** inject or filter tools. Agent Framework's MCP tool classes already register MCP tools natively, and a given MCP server may expose tools beyond skills — the adapter has no reliable way to tell which tools are skill tools, so attempting to filter them would be guesswork.

It also does not start or manage server processes, and does not import from `agentskills_mcp_server`'s server module. It only needs a generic MCP session, which makes it transport-agnostic across `MCPStdioTool`, `MCPSseTool`, and `MCPStreamableHttpTool`.

## Consequences

**Good**

- The base MCP package stays framework-agnostic; `agent-framework` is only pulled in when someone opts into the extra.
- Discoverable — MCP users find the adapter in the package they already installed, not a separate one they have to know exists.
- No tool duplication or fragile tool filtering.
- Works with any MCP transport, since only the session is required.

**Costs**

- `agentskills-mcp-server` now has framework-specific code in its tree, even though the dependency is optional. If a second framework adapter is ever needed, this pattern does not scale and the adapters should move to their own packages.
- Prompt-template validation is duplicated between the two context providers. Acceptable for two call sites; extract to a shared helper if a third appears.

## Alternatives considered

- **Put it in `agentskills-agentframework`.** Rejected: that package's contract is "wrap a registry in-process". Adding an MCP-session-based provider would give it two unrelated entry points and an MCP dependency it otherwise does not need.
- **A separate `agentskills-mcp-agentframework` package.** Rejected: a seventh package for one thin class, and users would have to discover it existed.
