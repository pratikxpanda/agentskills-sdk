---
title: Examples
description: Framework-owned MCP migration examples and retained native integration demonstrations.
---

LangChain and Microsoft Agent Framework examples organized by **provider** and **tool approach**.

## v0.6 Migration

Use the framework-owned MCP examples for new integrations. Native tools and the
SDK-owned context providers become deprecated and maintenance-only in v0.6.
They remain here for existing users during the migration window. Review the
[migration guide and feature gaps](../docs/mcp-migration.md) before replacing
automatic prompt injection or session pruning.

The filesystem MCP examples support `--smoke` for model-free checks and
`--server-python` for an isolated server interpreter. Run from the repository root:

```bash
python examples/langchain/fs/mcp_tools.py --smoke --server-python /path/to/server/python
python examples/agent-framework/fs/mcp_tools.py --smoke --server-python /path/to/server/python
```

These checks use legacy tools and resources. They do not certify native Skills
activation, host consent, or remote HTTP authentication.

## MCP Benchmarks

Run `python examples/mcp/benchmark.py --sizes 1 10 100 --repeats 3` with the
development checkout and MCP 2.2.0. The [benchmark guide](../docs/mcp-benchmarks.md)
defines the synthetic corpus, native and legacy workloads, metrics, and limitations.
The benchmark uses its own temporary skills and does not call a model.

## Structure

### LangChain

| Path | Provider | Tools | Description |
| --- | --- | --- | --- |
| `langchain/fs/local_tools.py` | Filesystem | LangChain native | Skills loaded from disk, converted to LangChain tools directly |
| `langchain/fs/mcp_tools.py` | Filesystem | MCP via LangChain | Skills served by an MCP server, consumed through `langchain-mcp-adapters` |
| `langchain/http/local_tools.py` | HTTP | LangChain native | Skills fetched from a URL, converted to LangChain tools directly |
| `langchain/http/mcp_tools.py` | HTTP | MCP via LangChain | Skills served by an MCP server (HTTP-backed), consumed through `langchain-mcp-adapters` |

### Agent Framework

| Path | Provider | Tools | Description |
| --- | --- | --- | --- |
| `agent-framework/fs/local_context_provider.py` | Filesystem | Context provider | Skills loaded from disk, injected automatically via `AgentSkillsContextProvider` |
| `agent-framework/http/local_context_provider.py` | HTTP | Context provider | Skills fetched from a URL, injected automatically via `AgentSkillsContextProvider` |
| `agent-framework/fs/local_tools.py` | Filesystem | Agent Framework native | Skills loaded from disk, converted to Agent Framework tools directly |
| `agent-framework/fs/mcp_tools.py` | Filesystem | MCP via Agent Framework | Skills served by an MCP server, consumed through `MCPStdioTool` (manual resource reading) |
| `agent-framework/fs/mcp_context_provider.py` | Filesystem | MCP context provider | Skills served by an MCP server, injected automatically via `AgentSkillsMcpContextProvider` |
| `agent-framework/http/local_tools.py` | HTTP | Agent Framework native | Skills fetched from a URL, converted to Agent Framework tools directly |
| `agent-framework/http/mcp_tools.py` | HTTP | MCP via Agent Framework | Skills served by an MCP server (HTTP-backed), consumed through `MCPStdioTool` (manual resource reading) |
| `agent-framework/http/mcp_context_provider.py` | HTTP | MCP context provider | Skills served by an MCP server (HTTP-backed), injected automatically via `AgentSkillsMcpContextProvider` |

## Local vs MCP Tools

**Local tools** - The `agentskills-langchain` or `agentskills-agentframework`
package converts skills into framework-native tool instances directly. Simplest
setup; no server process needed.

**MCP tools** - The `agentskills-mcp-server` package exposes skills through an MCP
server. LangChain uses `langchain-mcp-adapters` to bridge those MCP tools;
Agent Framework uses its built-in `MCPStdioTool`. Useful when you want a
standard MCP server that any MCP client can connect to.

**MCP context providers** (Agent Framework only) -
`AgentSkillsMcpContextProvider` wraps an MCP session and automatically reads
the skills catalog and usage instructions on every `agent.run()` call. It is
deprecated in v0.6. The MCP tools examples use the framework-owned client and
explicit resource reading instead, without automatically replacing session behavior.

## Prerequisites

Framework examples use the `incident-response` sample skill in `examples/skills/`.

### LangChain examples

```bash
# Core + provider + integration
pip install agentskills-core agentskills-fs agentskills-langchain

# For HTTP examples
pip install agentskills-http

# For MCP examples
pip install agentskills-mcp-server langchain-mcp-adapters

# For the LLM agent (optional - demos degrade gracefully)
pip install langchain langchain-openai
```

### Agent Framework examples

```bash
# Core + provider + integration
pip install agentskills-core agentskills-fs agentskills-agentframework

# For HTTP examples
pip install agentskills-http

# For MCP examples
pip install agentskills-mcp-server

# For MCP context provider examples
pip install agentskills-mcp-server[agentframework]

# Agent Framework (required)
pip install agent-framework --pre
```

Set the Azure OpenAI environment variables before running:

**Bash / Zsh:**

```bash
export AZURE_OPENAI_API_KEY=...
export AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
export AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
export AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

**PowerShell:**

```powershell
$env:AZURE_OPENAI_API_KEY = "..."
$env:AZURE_OPENAI_ENDPOINT = "https://<your-resource>.openai.azure.com"
$env:AZURE_OPENAI_DEPLOYMENT = "gpt-4o-mini"
$env:AZURE_OPENAI_API_VERSION = "2024-12-01-preview"
```

## Running

### Serving skills over HTTP (for HTTP examples)

The HTTP examples need a base URL that serves the skill files. The easiest way
is to start a local HTTP server from the `examples/skills/` directory:

**Bash / Zsh:**

```bash
# In a separate terminal
cd examples/skills
python -m http.server 8000

# Then set the base URL
export SKILLS_BASE_URL=http://localhost:8000
```

**PowerShell:**

```powershell
# In a separate terminal
cd examples\skills
python -m http.server 8000

# Then set the base URL
$env:SKILLS_BASE_URL = "http://localhost:8000"
```

The `HTTPStaticFileSkillProvider` expects `{base_url}/{skill_id}/SKILL.md`, which
maps to `http://localhost:8000/incident-response/SKILL.md` - matching the
directory structure exactly.

### Run LangChain examples

```bash
# Filesystem - local tools
python examples/langchain/fs/local_tools.py

# Filesystem - MCP tools
python examples/langchain/fs/mcp_tools.py

# HTTP - local tools (start the local HTTP server first, see above)
python examples/langchain/http/local_tools.py

# HTTP - MCP tools
python examples/langchain/http/mcp_tools.py
```

### Run Agent Framework examples

```bash
# Filesystem - existing deprecated context provider
python examples/agent-framework/fs/local_context_provider.py

# HTTP - existing deprecated context provider (start the local HTTP server first)
python examples/agent-framework/http/local_context_provider.py

# Filesystem - local tools
python examples/agent-framework/fs/local_tools.py

# Filesystem - MCP tools (manual resource reading)
python examples/agent-framework/fs/mcp_tools.py

# Filesystem - MCP context provider (recommended)
python examples/agent-framework/fs/mcp_context_provider.py

# HTTP - local tools (start the local HTTP server first, see above)
python examples/agent-framework/http/local_tools.py

# HTTP - MCP tools (manual resource reading)
python examples/agent-framework/http/mcp_tools.py

# HTTP - MCP context provider (recommended, start the local HTTP server first)
python examples/agent-framework/http/mcp_context_provider.py
```
