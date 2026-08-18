# agentskills-mcp-server

[![PyPI](https://img.shields.io/pypi/v/agentskills-mcp-server)](https://pypi.org/project/agentskills-mcp-server/)
[![Python 3.12 | 3.13](https://img.shields.io/pypi/pyversions/agentskills-mcp-server)](https://pypi.org/project/agentskills-mcp-server/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> MCP server integration for the [Agent Skills SDK](https://github.com/pratikxpanda/agentskills-sdk) - expose a skill registry as an MCP server.

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

With Agent Framework integration:

```bash
pip install agentskills-mcp-server[agentframework]  # MCP context provider for Agent Framework
```

Requires Python 3.12 or newer. Installs `agentskills-core`, `mcp`, and `pydantic` as dependencies.

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

Only `"fs"` and `"http"` are supported as provider types.

### Environment Variable Substitution

String values in the config file may contain `${VAR}` placeholders that are resolved from environment variables at load time:

```json
{
    "name": "My Skills Server",
    "skills": [
        {
            "id": "cloud-runbooks",
            "provider": "http",
            "options": {
                "base_url": "https://cdn.example.com/skills",
                "headers": { "Authorization": "Bearer ${API_TOKEN}" },
                "params": { "sig": "${SAS_TOKEN}" }
            }
        }
    ]
}
```

Unset variables resolve to an empty string and a warning is logged.

## Programmatic Usage

For custom providers or advanced setups, use the Python API directly:

```python
from agentskills_core import SkillRegistry
from agentskills_mcp_server import create_mcp_server

registry = SkillRegistry()
await registry.register("incident-response", my_custom_provider)  # any SkillProvider

server = create_mcp_server(registry, name="My Skills Server")
server.run()  # stdio by default
```

## Agent Framework Context Provider

If you're using [Microsoft Agent Framework](https://pypi.org/project/agent-framework/), `AgentSkillsMcpContextProvider` bridges an MCP session into the Agent Framework lifecycle. It reads the skills catalog and usage-instruction resources from the MCP server and injects them as session instructions on every `agent.run()` call.

> **Note:** This adapter only injects instructions, not tools. Agent Framework's MCP tool classes (`MCPStdioTool`, `MCPStreamableHttpTool`, etc.) handle tool registration natively.

```bash
pip install agentskills-mcp-server[agentframework]
```

```python
from agent_framework import Agent, MCPStdioTool
from agentskills_mcp_server import AgentSkillsMcpContextProvider

mcp_skills = MCPStdioTool(
    name="skills",
    command="python",
    args=["-m", "agentskills_mcp_server", "--config", "server.json"],
)

async with mcp_skills:
    skills_context = AgentSkillsMcpContextProvider(
        session=mcp_skills.session,
    )
    agent = Agent(
        client=client,  # any Agent Framework chat client
        name="SREAssistant",
        instructions="You are an SRE assistant.",
        tools=mcp_skills,
        context_providers=[skills_context],
    )
    response = await agent.run("What severity is a full DB outage?")
```

> See [examples/agent-framework/](https://github.com/pratikxpanda/agentskills-sdk/tree/main/examples/agent-framework) for full working demos including client setup.

| Parameter | Default | Description |
| --- | --- | --- |
| `session` | *(required)* | An MCP `ClientSession`, typically from `mcp_tool.session` |
| `skills_instruction_prompt` | Built-in template | Custom prompt template. Must contain `{skills_catalog}` and `{tools_usage_instructions}` placeholders. |
| `skills_catalog_format` | `"xml"` | Skills catalog format — `"xml"` or `"markdown"`. |
| `source_id` | `"agentskills_mcp"` | Unique identifier for this provider instance. |

## Tools

The server exposes tools that let the LLM agent access skill content:

| Tool | Parameters | Description |
| --- | --- | --- |
| `get_skill_metadata` | `skill_id` | Read frontmatter (name, description, etc.) |
| `get_skill_body` | `skill_id` | Load full skill instructions |
| `get_skill_outline` | `skill_id` | List the body's sections, keys and token costs |
| `get_skill_section` | `skill_id`, `key` | Load one section of the body |
| `list_skill_resources` | `skill_id` | List bundled references, scripts and assets |
| `get_skill_reference` | `skill_id`, `name` | Read a reference document |
| `get_skill_script` | `skill_id`, `name` | Read a script |
| `get_skill_asset` | `skill_id`, `name` | Read an asset |

`get_skill_outline` exists so a large skill is not all-or-nothing. Its rendered text carries the whole-body cost alongside the per-section costs and says outright when `get_skill_body` is the cheaper call — a section fetch is not free, it costs a tool call and a model turn on top of the outline. Section keys are flat slugs and sections do not nest, so fetching a parent does not include what is indented under it in the outline.

`list_skill_resources` returns a JSON object keyed by resource kind. Not every backend can enumerate resources — a plain static HTTP host cannot. Rather than surfacing an exception, the tool returns `{"supported": false, "note": "..."}` in that case: "this cannot be listed" is something the model can act on by falling back to the names in the skill body, not an error worth retrying.

## Resources

The server provides resources for system-prompt context:

| URI | Description |
| --- | --- |
| `skills://catalog/xml` | XML catalog of all registered skills |
| `skills://catalog/markdown` | Markdown catalog of all registered skills |
| `skills://tools-usage-instructions` | Workflow instructions for using the tools |
| `skills://{skill_id}/resources` | Resource listing for a single skill |

The MCP client reads these resources and injects them into the system prompt, giving the agent both *what* skills exist and *how* to interact with them.

## Single-Skill Fast Path

A server exposing one skill makes the client pay the whole discovery apparatus — a catalog listing one entry, eight tool definitions, usage instructions describing a selection workflow, and a model round trip while the agent calls `get_skill_body` — to reach content there was never a choice about.

```python
from agentskills_core import resolve_fast_path

fast_path = await resolve_fast_path(registry)
server = create_mcp_server(registry, name="my-skills", fast_path=fast_path)
```

`resolve_fast_path` returns `None` unless the effective skill set is exactly one and its body fits under a token ceiling, and `fast_path=None` is the normal path — so the call above is safe unconditionally. When it fires:

- Both `skills://catalog/*` resources serve the skill's body directly, so an existing client that already injects the catalog needs no change.
- `skills://tools-usage-instructions` drops the selection workflow, which would otherwise point the model at a catalog that is no longer there and at tools that are no longer registered.
- The four body-access tools are **never registered**. MCP has no way to hide a registered tool later, so they are omitted at construction rather than declined at call time.
- The four resource tools remain.

The ceiling, the arithmetic behind its default, and why resource tools stay are documented in the [core README](https://github.com/pratikxpanda/agentskills-sdk/tree/main/packages/core/agentskills-core#single-skill-fast-path). Because tools are fixed at construction, rebuild the server if the registry changes.

## API

### `AgentSkillsMcpContextProvider(session, *, skills_instruction_prompt=None, skills_catalog_format="xml", source_id=None)`

A `ContextProvider` that reads the skills catalog and tools-usage-instructions from an MCP session and injects them as session instructions via `before_run()`. Requires the `[agentframework]` extra.

### `create_mcp_server(registry, *, name, instructions=None, max_inline_binary_bytes=65536, fast_path=None) -> FastMCP`

| Parameter | Type | Description |
| --- | --- | --- |
| `registry` | `SkillRegistry` | The registry whose skills are exposed |
| `name` | `str` | Display name for the MCP server (required) |
| `instructions` | `str \| None` | Optional server-level instructions sent to clients |
| `max_inline_binary_bytes` | `int` | Size ceiling for inlining binary resources as base64 |
| `fast_path` | `FastPath \| None` | From `resolve_fast_path`; inlines a lone skill's body and drops the body-access tools |

Returns a configured `FastMCP` instance ready for `server.run()`.

Supported transport modes: `stdio` (default), `streamable-http`.

## Binary Resources

Skill resources may be arbitrary files. Valid UTF-8 is returned as-is; anything else is returned as a JSON envelope, so a binary payload is never silently mangled into replacement characters:

```json
{
  "name": "architecture.png",
  "media_type": "image/png",
  "size_bytes": 20481,
  "encoding": "base64",
  "content": "iVBORw0KGgo..."
}
```

Base64 costs roughly 1.37 characters per byte, so binaries above 64 KiB are described rather than inlined - `"encoding": "none"` plus a `note` explaining the omission. Adjust the ceiling with `create_mcp_server(..., max_inline_binary_bytes=256 * 1024)`.

## License

MIT
