# agentskills-mcp-server

[![PyPI](https://img.shields.io/pypi/v/agentskills-mcp-server)](https://pypi.org/project/agentskills-mcp-server/)
[![Python 3.12+](https://img.shields.io/pypi/pyversions/agentskills-mcp-server)](https://pypi.org/project/agentskills-mcp-server/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> MCP server integration for the [Agent Skills SDK](../../README.md) — expose a skill registry as an MCP server.

Creates a [Model Context Protocol](https://modelcontextprotocol.io/) server from a `SkillRegistry`, exposing skills as MCP tools and resources. Works with any MCP-compatible client (Claude Desktop, VS Code, custom clients, etc.).

## Installation

```bash
pip install agentskills-mcp-server
```

With provider extras:

```bash
pip install agentskills-mcp-server[fs]    # filesystem provider
pip install agentskills-mcp-server[http]  # HTTP provider
```

Requires Python 3.12+. Installs `agentskills-core`, `mcp`, and `pydantic` as dependencies.

## Quick Start (CLI)

Create a `server.json` config file:

```json
{
    "name": "My Skills Server",
    "skills": [
        {
            "id": "incident-response",
            "provider": "fs",
            "options": {"root": "./skills"}
        }
    ]
}
```

Start the server:

```bash
python -m agentskills_mcp_server --config server.json
```

With Streamable HTTP transport:

```bash
python -m agentskills_mcp_server --config server.json --transport streamable-http
```

The server listens on `http://127.0.0.1:8000/mcp`.

### MCP Client Integration

Any MCP-compatible client (Claude Desktop, VS Code, etc.) can connect to the server.

Stdio (local):

```json
{
    "command": "python",
    "args": ["-m", "agentskills_mcp_server", "--config", "server.json"]
}
```

Streamable HTTP (remote):

```json
{
    "url": "http://127.0.0.1:8000/mcp"
}
```

## Config Reference

The `server.json` file supports the following structure:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `str` | Yes | Display name shown to MCP clients |
| `instructions` | `str` | No | Server-level instructions sent during handshake |
| `skills` | `list` | Yes | One or more skill definitions (see below) |

Each skill entry:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | `str` | Yes | Skill identifier |
| `provider` | `str` | Yes | Provider type: `"fs"` or `"http"` |
| `options` | `dict` | No | Provider-specific options |

**Provider options:**

- **`fs`**: `root` (path to skills directory, default `"."`)
- **`http`**: `base_url` (required), `headers` (optional), `params` (optional query string parameters)

## Programmatic Usage

For custom providers or advanced setups, use the Python API directly:

```python
from agentskills_core import SkillRegistry
from agentskills_mcp_server import create_mcp_server

registry = SkillRegistry()
await registry.register("incident-response", my_custom_provider)

server = create_mcp_server(registry, name="My Skills Server")
server.run()  # stdio by default
```

## Tools

The server exposes tools that let the LLM agent access skill content:

| Tool | Parameters | Description |
| --- | --- | --- |
| `get_skill_metadata` | `skill_id` | Read frontmatter (name, description, etc.) |
| `get_skill_body` | `skill_id` | Load full skill instructions |
| `get_skill_reference` | `skill_id`, `name` | Read a reference document |
| `get_skill_script` | `skill_id`, `name` | Read a script |
| `get_skill_asset` | `skill_id`, `name` | Read an asset |

## Resources

The server provides resources for system-prompt context:

| URI | Description |
| --- | --- |
| `skills://catalog/xml` | XML catalog of all registered skills |
| `skills://catalog/markdown` | Markdown catalog of all registered skills |
| `skills://tools-usage-instructions` | Workflow instructions for using the tools |

The MCP client reads these resources and injects them into the system prompt, giving the agent both *what* skills exist and *how* to interact with them.

## API

### `create_mcp_server(registry, *, name, instructions=None) -> FastMCP`

| Parameter | Type | Description |
| --- | --- | --- |
| `registry` | `SkillRegistry` | The registry whose skills are exposed |
| `name` | `str` | Display name for the MCP server (required) |
| `instructions` | `str \| None` | Optional server-level instructions sent to clients |

Returns a configured `FastMCP` instance ready for `server.run()`.

## License

MIT
