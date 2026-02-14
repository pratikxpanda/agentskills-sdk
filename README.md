# Agent Skills SDK

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![GitHub repo](https://img.shields.io/github/stars/pratikxpanda/agentskills-sdk?style=social)](https://github.com/pratikxpanda/agentskills-sdk)

> A Python SDK for discovering, retrieving, and serving [Agent Skills](https://agentskills.io) to LLM agents.

**Agent Skills** is an [open format](https://agentskills.io/specification) for giving AI agents new capabilities and expertise. Originally developed by Anthropic, the format is now supported by Claude Code, Cursor, GitHub, VS Code, Gemini CLI, and many others.

This project helps you **integrate skills into your own agents**. Retrieve skills from any source — filesystem, database, API — validate them against the spec, and expose them to LLM agents through a progressive-disclosure API.

---

## Packages

| Package | Description | Install |
| --- | --- | --- |
| [`agentskills-core`](packages/core/agentskills-core/README.md) | Core abstractions — `SkillProvider`, `Skill`, `SkillRegistry`, validation | `pip install agentskills-core` |
| [`agentskills-fs`](packages/providers/agentskills-fs/README.md) | Load skills from the local filesystem — `LocalFileSystemSkillProvider` | `pip install agentskills-fs` |
| [`agentskills-http`](packages/providers/agentskills-http/README.md) | Load skills from a static HTTP server — `HTTPStaticFileSkillProvider` | `pip install agentskills-http` |
| [`agentskills-langchain`](packages/integrations/agentskills-langchain/README.md) | Integrate skills with LangChain agents — `get_tools`, `get_tools_usage_instructions` | `pip install agentskills-langchain` |
| [`agentskills-agentframework`](packages/integrations/agentskills-agentframework/README.md) | Integrate skills with Microsoft Agent Framework agents — `get_tools`, `get_tools_usage_instructions` | `pip install agentskills-agentframework` |
| [`agentskills-mcp-server`](packages/integrations/agentskills-mcp-server/README.md) | Expose skills over the Model Context Protocol (MCP) — `create_mcp_server` | `pip install agentskills-mcp-server` |

## How It Works

The SDK uses **progressive disclosure** to deliver skill content efficiently — each step only fetches what's needed:

1. **Register** skills from any source (filesystem, HTTP, database, etc.)
2. **Inject** the skills catalog and tool usage instructions into the system prompt
3. **Disclose on demand** — the agent uses tools (`get_skill_body`, `get_skill_reference`, etc.) to retrieve content as needed

The system prompt tells the agent *what* skills exist and *how* to use the tools. The tools themselves are the progressive-disclosure API — the agent fetches metadata, then the full body, then individual references, scripts, or assets, only when needed.

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

```python
from agentskills_mcp_server import create_mcp_server

server = create_mcp_server(registry, name="My Agent")
server.run()  # stdio by default
```

The server exposes tools (`get_skill_metadata`, `get_skill_body`, etc.) and resources (`skills://catalog/xml`, `skills://catalog/markdown`, `skills://tools-usage-instructions`). The MCP client reads the resources and injects them into the system prompt, then uses the tools for on-demand content retrieval.

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

Register multiple providers together:

```python
registry = SkillRegistry()
await registry.register([
    ("db-skill", DatabaseSkillProvider(conn)),
    ("incident-response", LocalFileSystemSkillProvider(path)),
])
```

Batch registration is atomic — if any skill fails validation, none are registered.

## Development

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for setup, testing, linting, and project structure.

## Related Resources

- [Agent Skills specification](https://agentskills.io/specification)
- [What are skills?](https://agentskills.io/what-are-skills)
- [Integrate skills into your agent](https://agentskills.io/integrate-skills)
- [Example skills](https://github.com/anthropics/skills) on GitHub

## Contributing

Contributions are welcome! Please open an issue to discuss your idea before submitting a PR.

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Make your changes with tests
4. Run `poetry run pytest packages/` and ensure all tests pass
5. Open a pull request

## License

MIT
