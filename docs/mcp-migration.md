---
title: MCP Migration
description: Migrate native framework integrations to framework-owned MCP clients with explicit compatibility limits.
---

## Deprecation Window

v0.6.0 deprecates `agentskills-langchain`,
`agentskills-agentframework`, `AgentSkillsMcpContextProvider`, and the
`agentskills-mcp-server[agentframework]` extra. Published 0.5.0 wheels are unchanged.
These surfaces receive critical correctness and security fixes only. They remain
in lockstep releases during the migration window, with no API removal in v0.6.

Removal is no earlier than v0.7 and requires at least one full minor-release
migration window after deprecation ships, tested replacements, documented gaps,
and a breaking-change notice. Existing wheels and versioned documentation will
remain available. No package will be yanked solely because it was retired.

Core, providers, retrieval, testing, CLI tooling, and `agentskills-mcp-server`
remain maintained. `agentskills-adapters` imports foreign instruction formats
and is not part of this retirement.

`get_tools()` in either native integration emits `DeprecationWarning`.
Constructing `AgentSkillsContextProvider` or `AgentSkillsMcpContextProvider`
also emits one warning attributed to the caller. Imports remain quiet. Python
normally hides library deprecation warnings, so use `python -W default` when
auditing an application. Warning messages link to this migration guide.

## Choose a Delivery Mode

Use the maintained legacy MCP server with framework-owned MCP clients when your
host only supports MCP tools and resources. The eight `get_skill_*` and resource
listing tools, catalog resources, and section disclosure remain available.
The examples below use this compatibility mode. They do not demonstrate native
Skills activation.

Use native mode only with a host that implements the Skills extension and its
consent and verification responsibilities. It requires server SDK 2.2+ and
protocol 2026-07-28. Discovery returns manifests, not inlined instructions.
An older client reading a `skill://` resource does not establish native support.
See the [tested transport matrix](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/integrations/agentskills-mcp-server/README.md) and the
[roadmap](ROADMAP.md#native-integration-retirement).

## Verified Framework Replacements

Checked 2026-10-06 with `langchain-mcp-adapters` 0.3.2, `langchain-core` 1.6.5,
and `agent-framework-core` 1.12.1 in a client environment using MCP 1.29.0.
Both clients connected to the checkout's legacy server on MCP 2.2.0 in a separate
process. The checks loaded eight framework tools, read the catalog and usage
instructions, and invoked `get_skill_body` through the framework-owned client.
They did not call an LLM or verify model behavior.

Run the commands below from the repository root. In a dedicated server environment,
install this checkout to reproduce the examples:

```bash
python -m pip install "mcp==2.2.0" ./packages/core/agentskills-core ./packages/providers/agentskills-fs ./packages/integrations/agentskills-mcp-server
```

In a separate client environment, install the tested clients:

```bash
python -m pip install "mcp==1.29.0" "langchain-mcp-adapters==0.3.2" "agent-framework-core==1.12.1"
```

Replace the server executable placeholder with its actual path. On Windows it
is normally the server environment's `Scripts/python.exe`.

```bash
python examples/langchain/fs/mcp_tools.py --smoke --server-python /absolute/path/to/server/python
python examples/agent-framework/fs/mcp_tools.py --smoke --server-python /absolute/path/to/server/python
```

The smoke mode fails nonzero on a missing dependency or failed MCP check and has
a 30-second deadline. It needs no model credentials. Omitting `--smoke` retains
the interactive agent examples and their optional model dependencies.

### LangChain

Replace `agentskills_langchain.get_tools()` with `MultiServerMCPClient` from
`langchain_mcp_adapters.client`. The existing
[filesystem example](https://github.com/pratikxpanda/agentskills-sdk/blob/main/examples/langchain/fs/mcp_tools.py)
reads the legacy catalog and usage-instruction resources explicitly and obtains
framework tools with `client.get_tools()`.

That API opens a new MCP session for each tool call. For a persistent session,
use `client.session("skills")` and `load_mcp_tools(session)` from
`langchain_mcp_adapters.tools`, keeping the session open for the entire agent run.
Do not use session-bound tools after leaving that context. Prompt resources read
earlier do not automatically refresh when a later session reconnects.

### Microsoft Agent Framework

Replace `agentskills_agentframework.get_tools()` and the SDK context providers
with `MCPStdioTool` from `agent_framework`. Keep it open with `async with` for
the entire agent run and pass it to the agent's `tools` parameter. The
[filesystem example](https://github.com/pratikxpanda/agentskills-sdk/blob/main/examples/agent-framework/fs/mcp_tools.py)
reads prompt resources explicitly through `mcp_skills.session` and demonstrates
model-free invocation through `mcp_skills.call_tool()`.

The verified framework client requires MCP 1.x. Keep it separate from an SDK 2
server rather than forcing incompatible dependencies into one environment.
The replacement does not reproduce `before_run` catalog injection, prompt
caching, or session pruning automatically.

## Feature-Gap Matrix

| Existing behavior | Maintained replacement | Remaining responsibility or gap |
| --- | --- | --- |
| Native framework tool wrappers | Framework-owned MCP clients consume the eight legacy tools | Verified tool discovery and a body call, not every model/provider combination |
| Automatic catalog injection | Read `skills://catalog/xml` and `skills://tools-usage-instructions` explicitly | Application chooses when to refresh and inject, and avoids duplicate injection |
| Query-time retrieval | Framework-neutral `agentskills-retrieval` remains maintained | Host integration is required, not automatically attached to remote MCP clients |
| Cached prompts and loaded-skill session pruning | Existing native context provider remains during migration | Host must implement conversation-aware caching and pruning before removal |
| Single-skill fast path | Framework-neutral core API and legacy server option remain available | Not automatic in the example or native discovery, which stays metadata-only |
| Section-level disclosure | Legacy outline and section tools remain available | Native Skills requires full canonical resources, not proprietary section tools |
| Vision-native assets | Legacy server retains opt-in image tool delivery | Native resources preserve original blobs, host decoding and rendering are required |
| Context-provider metadata about loaded skills | Host-owned session state | No automatic replacement for `METADATA_LOADED_SKILLS` in framework clients |
| Native Skills verification and activation | A conforming Skills host | Ordinary MCP tool connectivity does not supply consent, digest checks, or activation |

Gaps are not removal approvals. Keep the deprecated integration until your
application has implemented and tested the behavior it relies on. Before removal,
each remaining gap needs a documented alternative and an explicit migration
decision, rather than an assumption that successful tool calls imply parity.

## Trust and Deployment Boundaries

The smoke examples use the repository's trusted sample skills. Applications must
choose trusted servers, isolate skill identity by server and URI, and control
which content enters the model context. Reading scripts does not execute them.
Listing filters are not authorization, and `allowed-tools` does not grant host
permissions. A matching digest proves consistency, not publisher trust.

A native host must verify the complete manifest, size, digests, and frontmatter,
obtain per-skill consent, and treat nested skills as separate approval decisions.
Fetch content only when needed. Remote HTTP additionally requires appropriate
authentication, TLS, origin checks, and audience isolation. These examples do not
certify those deployment controls.

## v0.6 Release-Note Guidance

Native LangChain and Microsoft Agent Framework integrations, the Agent Framework
MCP context-provider bridge, and its optional extra are deprecated and
maintenance-only. Existing APIs remain available throughout v0.6. Migrate using
framework-owned MCP clients and review the feature-gap matrix before replacing
context-provider behavior. The maintained MCP server and foreign-format adapters
are unaffected by this deprecation. No retirement or package publication has been
performed by this development change.
