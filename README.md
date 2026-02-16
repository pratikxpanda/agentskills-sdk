# Agent Skills SDK

[![CI](https://github.com/pratikxpanda/agentskills-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/pratikxpanda/agentskills-sdk/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![GitHub repo](https://img.shields.io/github/stars/pratikxpanda/agentskills-sdk?style=social)](https://github.com/pratikxpanda/agentskills-sdk)

> A Python SDK for discovering, retrieving, and serving [Agent Skills](https://agentskills.io) to LLM agents.

**Agent Skills** is an [open format](https://agentskills.io/specification) for giving AI agents new capabilities and expertise. Originally developed by Anthropic, the format is now supported by Claude Code, Cursor, GitHub, VS Code, Gemini CLI, and many others.

This project helps you **integrate skills into your own agents**. Retrieve skills from any source - filesystem, database, API - validate them against the spec, and expose them to LLM agents through a progressive-disclosure API.

> **Note:** Python 3.12 and 3.13 are fully tested. Python 3.14 is not yet supported due to upstream dependency limitations (`agentskills-langchain` and `agentskills-agentframework`).

---

## Packages

| Package | Description | Install |
| --- | --- | --- |
| [`agentskills-core`](packages/core/agentskills-core/README.md) | Core abstractions - `SkillProvider`, `Skill`, `SkillRegistry`, validation | `pip install agentskills-core` |
| [`agentskills-fs`](packages/providers/agentskills-fs/README.md) | Load skills from the local filesystem - `LocalFileSystemSkillProvider` | `pip install agentskills-fs` |
| [`agentskills-http`](packages/providers/agentskills-http/README.md) | Load skills from a static HTTP server - `HTTPStaticFileSkillProvider` | `pip install agentskills-http` |
| [`agentskills-langchain`](packages/integrations/agentskills-langchain/README.md) | Integrate skills with LangChain agents - `get_tools`, `get_tools_usage_instructions` | `pip install agentskills-langchain` |
| [`agentskills-agentframework`](packages/integrations/agentskills-agentframework/README.md) | Integrate skills with Microsoft Agent Framework agents - `get_tools`, `get_tools_usage_instructions` | `pip install agentskills-agentframework` |
| [`agentskills-mcp-server`](packages/integrations/agentskills-mcp-server/README.md) | Expose skills over the Model Context Protocol (MCP) - `create_mcp_server` | `pip install agentskills-mcp-server` |

## How It Works

The SDK uses **progressive disclosure** to deliver skill content efficiently - each step only fetches what's needed:

1. **Register** skills from any source (filesystem, HTTP, database, etc.)
2. **Inject** the skills catalog and tool usage instructions into the system prompt
3. **Disclose on demand** - the agent uses tools (`get_skill_body`, `get_skill_reference`, etc.) to retrieve content as needed

The system prompt tells the agent *what* skills exist and *how* to use the tools. The tools themselves are the progressive-disclosure API - the agent fetches metadata, then the full body, then individual references, scripts, or assets, only when needed.

## Quick Start

```python
import asyncio
from pathlib import Path
from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider

async def main():
    provider = LocalFileSystemSkillProvider(Path("my-skills"))
    registry = SkillRegistry()
    await registry.register("incident-response", provider)

    # Discover
    for skill in registry.list_skills():
        print(skill.get_id())                  # 'incident-response'

    # Retrieve
    skill = registry.get_skill("incident-response")
    meta = await skill.get_metadata()
    print(meta["description"])                 # SOPs for production incident management...
    print(await skill.get_body())              # Full markdown instructions

asyncio.run(main())
```

### With LangChain

```python
from langchain.agents import create_agent
from langchain_openai import AzureChatOpenAI
from agentskills_langchain import get_tools, get_tools_usage_instructions

tools = get_tools(registry)
skills_catalog = await registry.get_skills_catalog(format="xml")
tool_usage_instructions = get_tools_usage_instructions()

llm = AzureChatOpenAI(
    azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    temperature=0,
)
agent = create_agent(
    llm,
    tools,
    system_prompt=f"{skills_catalog}\n\n{tool_usage_instructions}",
)
```

The skill catalog tells the agent *what* skills exist, and the usage instructions tell it *how* to use the tools (`get_skill_body`, `get_skill_reference`, etc.).

See [examples/langchain/](examples/langchain/) for full working demos with filesystem and HTTP providers.

### With Microsoft Agent Framework

```python
from agent_framework import Agent
from agent_framework.azure import AzureOpenAIChatClient
from agentskills_agentframework import get_tools, get_tools_usage_instructions

tools = get_tools(registry)
skills_catalog = await registry.get_skills_catalog(format="xml")
tool_usage_instructions = get_tools_usage_instructions()

client = AzureOpenAIChatClient(
    deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
)
agent = Agent(
    client=client,
    instructions=f"{skills_catalog}\n\n{tool_usage_instructions}",
    tools=tools,
)
```

See [examples/agent-framework/](examples/agent-framework/) for full working demos with filesystem and HTTP providers.

### With MCP

#### Config-driven server (CLI)

Create a `server.json` config file and run the built-in MCP server directly - any MCP-compatible client (Claude Desktop, VS Code, Cursor, etc.) can connect to it:

```json
{
    "name": "My Skills Server",
    "skills": [
        {
            "id": "incident-response",
            "provider": "fs",
            "options": { "root": "./skills" }
        },
        {
            "id": "cloud-runbooks",
            "provider": "http",
            "options": {
                "base_url": "https://cdn.example.com/skills",
                "headers": { "Authorization": "Bearer ${API_TOKEN}" }
            }
        }
    ]
}
```

> **Environment variables** - String values may contain `${VAR}` placeholders that are resolved from environment variables at load time. This keeps secrets out of the config file.

```bash
# stdio transport (default - used by most MCP clients)
python -m agentskills_mcp_server --config server.json

# streamable-http transport
python -m agentskills_mcp_server --config server.json --transport streamable-http
```

Point your MCP client at the server:

```json
{
    "command": "python",
    "args": ["-m", "agentskills_mcp_server", "--config", "server.json"]
}
```

#### Programmatic server

For custom setups, create the server in code:

```python
from agentskills_mcp_server import create_mcp_server

server = create_mcp_server(registry, name="My Agent")
server.run()  # stdio by default
```

Both approaches expose the same tools (`get_skill_metadata`, `get_skill_body`, etc.) and resources (`skills://catalog/xml`, `skills://catalog/markdown`, `skills://tools-usage-instructions`).

## Custom Providers

The `SkillProvider` ABC is storage-agnostic. Implement it to back skills with any source:

```python
from agentskills_core import SkillProvider

class DatabaseSkillProvider(SkillProvider):
    async def get_metadata(self, skill_id: str) -> dict: ...
    async def get_body(self, skill_id: str) -> str: ...
    async def get_script(self, skill_id: str, name: str) -> bytes: ...
    async def get_asset(self, skill_id: str, name: str) -> bytes: ...
    async def get_reference(self, skill_id: str, name: str) -> bytes: ...
```

Register a custom provider:

```python
registry = SkillRegistry()
await registry.register("customer-onboarding", DatabaseSkillProvider(conn))
```

Register multiple providers at once:

```python
registry = SkillRegistry()
await registry.register([
    ("customer-onboarding", DatabaseSkillProvider(conn)),
    ("incident-response", LocalFileSystemSkillProvider(path)),
])
```

Batch registration is atomic - if any skill fails validation, none are registered.

## Development

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for setup, testing, linting, CI, releasing, and project structure.

## Related Resources

- [Agent Skills specification](https://agentskills.io/specification)
- [What are skills?](https://agentskills.io/what-are-skills)
- [Integrate skills into your agent](https://agentskills.io/integrate-skills)
- [Agent Skills Directory](docs/SKILLS-DIRECTORY.md)

## Security

Agent Skills are **equivalent to executable code** - skill content is injected into an LLM agent's context verbatim. **Only load skills from sources you trust.**

The SDK includes built-in protections: input validation, TLS enforcement options, response size limits, path-traversal guards, and safe XML generation. See each package's README for provider-specific security controls.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on setup, code style, testing, and pull requests.

## License

MIT
