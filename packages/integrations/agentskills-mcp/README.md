# agentskills-modelcontextprotocol

[![PyPI](https://img.shields.io/pypi/v/agentskills-modelcontextprotocol)](https://pypi.org/project/agentskills-modelcontextprotocol/)
[![Python 3.12+](https://img.shields.io/pypi/pyversions/agentskills-modelcontextprotocol)](https://pypi.org/project/agentskills-modelcontextprotocol/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> MCP server integration for the [Agent Skills SDK](../../README.md) — expose a skill registry as an MCP server.

Creates a [Model Context Protocol](https://modelcontextprotocol.io/) server from a `SkillRegistry`, exposing skills as MCP tools and resources. Works with any MCP-compatible client (Claude Desktop, VS Code, custom clients, etc.).

## Installation

```bash
pip install agentskills-modelcontextprotocol
```

Requires Python 3.12+. Installs `agentskills-core` and `mcp` as dependencies.

## Usage

```python
from pathlib import Path
from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_mcp import create_mcp_server

provider = LocalFileSystemSkillProvider(Path("./skills"))
registry = SkillRegistry()
await registry.register("incident-response", provider)

server = create_mcp_server(registry, name="My Skills Server")
server.run()  # stdio by default
```

For HTTP transport:

```python
server.run(transport="streamable-http")
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
