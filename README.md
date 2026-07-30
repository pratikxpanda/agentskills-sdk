# Agent Skills SDK

[![CI](https://github.com/pratikxpanda/agentskills-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/pratikxpanda/agentskills-sdk/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/downloads/)

> A Python SDK for discovering, retrieving, and serving [Agent Skills](https://agentskills.io) to LLM agents.

**Agent Skills** is an [open format](https://agentskills.io/specification) for giving AI agents new capabilities and expertise. Originally developed by Anthropic, the format is now supported by Claude Code, Cursor, GitHub, VS Code, Gemini CLI, and many others.

This project helps you **integrate skills into your own agents**. Retrieve skills from any source - filesystem, database, API - validate them against the spec, and expose them to LLM agents through a progressive-disclosure API.

> **Note:** Requires Python 3.12 or newer. Tested against 3.12, 3.13, and 3.14.

---

## Packages

| Package | Description | Version | Downloads |
| --- | --- | --- | --- |
| [`agentskills-core`](packages/core/agentskills-core/README.md) | The registry, the provider interface, and spec validation. Every other package depends on it. | [![PyPI](https://img.shields.io/pypi/v/agentskills-core?label=)](https://pypi.org/project/agentskills-core/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-core?label=)](https://pepy.tech/project/agentskills-core) |
| [`agentskills-fs`](packages/providers/agentskills-fs/README.md) | **Provider** - read skills from a local directory. | [![PyPI](https://img.shields.io/pypi/v/agentskills-fs?label=)](https://pypi.org/project/agentskills-fs/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-fs?label=)](https://pepy.tech/project/agentskills-fs) |
| [`agentskills-http`](packages/providers/agentskills-http/README.md) | **Provider** - read skills from a static HTTP server or CDN. | [![PyPI](https://img.shields.io/pypi/v/agentskills-http?label=)](https://pypi.org/project/agentskills-http/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-http?label=)](https://pepy.tech/project/agentskills-http) |
| [`agentskills-langchain`](packages/integrations/agentskills-langchain/README.md) | **Integration** - expose skills to a LangChain agent as tools. | [![PyPI](https://img.shields.io/pypi/v/agentskills-langchain?label=)](https://pypi.org/project/agentskills-langchain/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-langchain?label=)](https://pepy.tech/project/agentskills-langchain) |
| [`agentskills-agentframework`](packages/integrations/agentskills-agentframework/README.md) | **Integration** - expose skills to a Microsoft Agent Framework agent, injected automatically through the agent lifecycle. | [![PyPI](https://img.shields.io/pypi/v/agentskills-agentframework?label=)](https://pypi.org/project/agentskills-agentframework/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-agentframework?label=)](https://pepy.tech/project/agentskills-agentframework) |
| [`agentskills-mcp-server`](packages/integrations/agentskills-mcp-server/README.md) | **Integration** - serve skills over the Model Context Protocol to any MCP client, such as Claude Desktop, VS Code, or Cursor. | [![PyPI](https://img.shields.io/pypi/v/agentskills-mcp-server?label=)](https://pypi.org/project/agentskills-mcp-server/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-mcp-server?label=)](https://pepy.tech/project/agentskills-mcp-server) |

**Which do I need?** One provider for wherever your skills live, plus the integration for your
agent framework. Both pull in `agentskills-core`, so a LangChain app reading skills from disk
needs only:

```bash
pip install agentskills-fs agentskills-langchain
```

## How It Works

The SDK uses **progressive disclosure** to deliver skill content efficiently - each step only fetches what's needed:

1. **Register** skills from any source (filesystem, HTTP, database, etc.)
2. **Inject** the skills catalog and tool usage instructions into the system prompt
3. **Disclose on demand** - the agent uses tools (`get_skill_body`, `get_skill_reference`, etc.) to retrieve content as needed

The system prompt tells the agent *what* skills exist and *how* to use the tools. The tools themselves are the progressive-disclosure API - the agent fetches metadata, then the full body, then individual references, scripts, or assets, only when needed.

## What a Skill Looks Like

A skill is a folder containing a `SKILL.md`. Everything else is optional:

```text
my-skills/
└── incident-response/
    ├── SKILL.md                        # required - frontmatter + markdown instructions
    ├── references/                     # optional - supporting documents
    │   └── severity-levels.md
    ├── scripts/                        # optional - retrieved for the agent, never executed by the SDK
    │   └── page-oncall.sh
    └── assets/                         # optional - diagrams, templates, other files
        └── escalation-flowchart.mermaid
```

`SKILL.md` is YAML frontmatter followed by markdown. Only `name` and `description` are required:

```markdown
---
name: incident-response
description: Standard operating procedures for production incident management including severity classification, escalation paths, communication protocols, and postmortem processes.
---

# Incident Response

This skill provides structured guidance for handling production incidents.

## When to Declare an Incident

- A production service is degraded or unavailable for users
- Data integrity may be compromised
...
```

The `description` is the only part the agent sees on every turn — it is what the agent uses to
decide whether to load the skill at all. Write it to say **when** the skill applies, not just what
it contains.

### Versioning a skill

`version` is an **optional** field. When present it must be a quoted [semver](https://semver.org)
string, and it appears in the skill catalog so an agent can tell versions apart:

```yaml
---
name: incident-response
description: Standard operating procedures for production incident management.
version: "1.2.0"
---
```

Quote it. Unquoted YAML reads `1.0` as a number and `2024-01-15` as a date, and registration will
reject both. An invalid version fails registration rather than being silently ignored — a version
nobody can rely on is worse than none.

`version` is **not** part of the upstream Agent Skills specification. It is supported here because
pinning and drift detection are not possible without it; the field is being raised upstream rather
than kept as a permanent proprietary extension.

See [examples/skills/incident-response/](examples/skills/incident-response/) for a complete skill
with references, scripts, and assets.

## Quick Start

```python
import asyncio
from pathlib import Path
from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider

async def main():
    registry = SkillRegistry()
    await registry.register(
        "incident-response",
        LocalFileSystemSkillProvider(Path("my-skills")),
    )

    # What the agent sees on every turn: names and descriptions, nothing more.
    print(await registry.get_skills_catalog(format="xml"))

    # What it fetches only after deciding the skill is relevant.
    skill = registry.get_skill("incident-response")
    print(await skill.get_body())

asyncio.run(main())
```

Those two calls are the whole idea. The catalog is small and always present; the body is large and
loaded on demand. Put the catalog in your system prompt, hand the agent the tools below, and it
makes the second call itself, only when it needs to.
```

### With LangChain

```python
import os

from langchain.agents import create_agent
from langchain_openai import AzureChatOpenAI
from agentskills_langchain import get_tools, get_tools_usage_instructions

tools = get_tools(registry)
skills_catalog = await registry.get_skills_catalog(format="xml")
tools_usage_instructions = get_tools_usage_instructions()

llm = AzureChatOpenAI(
    azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    temperature=0,
)
agent = create_agent(
    llm,
    tools,
    system_prompt=f"{skills_catalog}\n\n{tools_usage_instructions}",
)
```

The skill catalog tells the agent *what* skills exist, and the usage instructions tell it *how* to use the tools (`get_skill_body`, `get_skill_reference`, etc.).

See [examples/langchain/](examples/langchain/) for full working demos with filesystem and HTTP providers.

### With Microsoft Agent Framework

**Context provider (recommended)** — plug into the agent lifecycle so skills are injected automatically:

```python
from agent_framework import Agent
from agentskills_agentframework import AgentSkillsContextProvider

skills_context_provider = AgentSkillsContextProvider(registry)

agent = Agent(
    client=client,  # any Agent Framework chat client
    name="SREAssistant",
    instructions="You are an SRE assistant.",
    context_providers=[skills_context_provider],
)
response = await agent.run("What severity is a full DB outage?")
```

**Manual tools** — build the system prompt yourself for full control:

```python
from agent_framework import Agent
from agentskills_agentframework import get_tools, get_tools_usage_instructions

tools = get_tools(registry)
skills_catalog = await registry.get_skills_catalog(format="xml")
tools_usage_instructions = get_tools_usage_instructions()

agent = Agent(
    client=client,  # any Agent Framework chat client
    name="SREAssistant",
    instructions=f"{skills_catalog}\n\n{tools_usage_instructions}",
    tools=tools,
)
```

See [examples/agent-framework/](examples/agent-framework/) for full working demos including client setup.

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

#### Agent Framework + MCP context provider

If you're using Agent Framework with an MCP-based skill server, `AgentSkillsMcpContextProvider` bridges the MCP session into the agent lifecycle — skills are injected automatically on every `agent.run()` call:

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
    skills_context = AgentSkillsMcpContextProvider(session=mcp_skills.session)
    agent = Agent(
        client=client,
        name="SREAssistant",
        instructions="You are an SRE assistant.",
        tools=mcp_skills,
        context_providers=[skills_context],
    )
    response = await agent.run("What severity is a full DB outage?")
```

See [examples/agent-framework/](examples/agent-framework/) for full working demos.

## Custom Providers

The `SkillProvider` ABC is storage-agnostic. Implement it to back skills with any source:

```python
from agentskills_core import SkillProvider, SkillRegistry

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
await registry.register("customer-onboarding", DatabaseSkillProvider(conn))  # conn: your DB handle
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

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md) for planned themes, non-goals, and how work is tracked.

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
