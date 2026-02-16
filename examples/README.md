# Examples

LangChain and Microsoft Agent Framework examples organized by **provider** and **tool approach**.

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
| `agent-framework/fs/local_tools.py` | Filesystem | Agent Framework native | Skills loaded from disk, converted to Agent Framework tools directly |
| `agent-framework/fs/mcp_tools.py` | Filesystem | MCP via Agent Framework | Skills served by an MCP server, consumed through `MCPStdioTool` |
| `agent-framework/http/local_tools.py` | HTTP | Agent Framework native | Skills fetched from a URL, converted to Agent Framework tools directly |
| `agent-framework/http/mcp_tools.py` | HTTP | MCP via Agent Framework | Skills served by an MCP server (HTTP-backed), consumed through `MCPStdioTool` |

## Local vs MCP Tools

**Local tools** - The `agentskills-langchain` or `agentskills-agentframework`
package converts skills into framework-native tool instances directly. Simplest
setup; no server process needed.

**MCP tools** - The `agentskills-mcp-server` package exposes skills through an MCP
server. LangChain uses `langchain-mcp-adapters` to bridge those MCP tools;
Agent Framework uses its built-in `MCPStdioTool`. Useful when you want a
standard MCP server that any MCP client can connect to.

## Prerequisites

All examples use the `incident-response` sample skill in `examples/skills/`.

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
# Filesystem - local tools
python examples/agent-framework/fs/local_tools.py

# Filesystem - MCP tools
python examples/agent-framework/fs/mcp_tools.py

# HTTP - local tools (start the local HTTP server first, see above)
python examples/agent-framework/http/local_tools.py

# HTTP - MCP tools
python examples/agent-framework/http/mcp_tools.py
```
