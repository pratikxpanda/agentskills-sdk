# Agent Skills SDK

[![CI](https://github.com/pratikxpanda/agentskills-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/pratikxpanda/agentskills-sdk/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A596%25-brightgreen.svg)](https://github.com/pratikxpanda/agentskills-sdk/actions/workflows/ci.yml)
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
| [`agentskills-cli`](packages/cli/agentskills-cli/README.md) | **Tooling** - the `agentskills` command: scaffold, validate, lint, and inspect skills. | [![PyPI](https://img.shields.io/pypi/v/agentskills-cli?label=)](https://pypi.org/project/agentskills-cli/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-cli?label=)](https://pepy.tech/project/agentskills-cli) |
| [`agentskills-testing`](packages/testing/agentskills-testing/README.md) | **Tooling** - the provider conformance suite and an in-memory provider, for anyone writing a provider or testing against one. | [![PyPI](https://img.shields.io/pypi/v/agentskills-testing?label=)](https://pypi.org/project/agentskills-testing/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-testing?label=)](https://pepy.tech/project/agentskills-testing) |

**Which do I need?** One provider for wherever your skills live, plus the integration for your
agent framework. Both pull in `agentskills-core`, so a LangChain app reading skills from disk
needs only:

```bash
pip install agentskills-fs agentskills-langchain
```

If you *write* skills rather than consume them, you want `agentskills-cli` instead.

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

    # Registers every skill folder under my-skills/, no IDs to hard-code.
    await registry.register_all(LocalFileSystemSkillProvider(Path("my-skills")))

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

"Small" stops being automatic once a registry grows, and the catalog is a fixed cost on every
request. Narrow it, and cap it:

```python
catalog = await registry.get_skills_catalog(
    tags=["incident"],              # any-of match on metadata.tags
    exclude=["deprecated-runbook"], # deny-list of skill IDs
    max_chars=8000,                 # hard ceiling on the returned string
)
```

`max_chars` drops whole entries from the end until the result fits, and says so in the output —
the XML root gains `truncated`, `shown` and `total` attributes. A catalog that shrinks without
saying so makes agent behaviour non-reproducible.

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

## Command Line

`agentskills-cli` is for authoring skills rather than consuming them.

```bash
pip install agentskills-cli
```

```bash
agentskills init incident-response --path ./skills   # scaffold a skill that validates
agentskills validate ./skills                        # exits 1 on any error
agentskills lint ./skills                            # legal, but costly
agentskills inspect ./skills/incident-response       # what the agent actually receives
agentskills serve ./skills                           # MCP server, no config file
```

`validate` is the one to put in CI. It exits `1` when a skill is broken and `2` when the
invocation is, so a workflow can tell those apart, and `--format json` emits a documented,
versioned schema.

See the [package README](packages/cli/agentskills-cli/README.md) for the lint rules, the JSON
schema, and the exit codes.

### GitHub Action

If your skills live in a GitHub repository, the action wraps `validate` and `lint` and puts every
finding on the pull request diff, on the line that caused it:

```yaml
name: Skills
on: [pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: pratikxpanda/agentskills-sdk/actions/validate@v1
        with:
          path: ./skills
          fail-on-lint: false
```

| Input | Default | Purpose |
| --- | --- | --- |
| `path` | `.` | A skill folder, or a folder of skill folders. |
| `fail-on-lint` | `false` | Fail on lint warnings too. They are annotated either way. |
| `max-body-tokens` | CLI default | Body token budget before lint warns. |
| `version` | latest | Version of `agentskills-cli` to install. An `agentskills` already on `PATH` is used as-is, so a repository that pins the CLI keeps its pin. |
| `python-version` | `3.12` | Python to install the CLI on, when it installs one. |

Lint runs only after `validate` passes. Linting a skill whose frontmatter did not parse repeats
the same annotation, and a token budget is not the thing to fix first.

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

### Resource listing

`list_resources()` lets an agent discover which references, scripts, and assets a skill has,
instead of inferring them from the prose in `SKILL.md`. It is **optional**, because some backends
genuinely cannot enumerate — a static CDN has no directory listing.

Providers that can enumerate override the method and advertise it:

```python
class DatabaseSkillProvider(SkillProvider):
    supports_resource_listing = True

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        return {"references": [...], "scripts": [...], "assets": [...]}
```

Leave both alone and the default raises `ResourceListingNotSupportedError`. That is deliberate:
returning an empty dict would tell an agent the skill *has* no resources, when the truth is that
this provider cannot say. `LocalFileSystemSkillProvider` supports listing; the HTTP provider does
so only when the skill publishes an `index.json`.

### Skill discovery

`discover()` is the same idea one level up: it returns the IDs of every skill the backend holds,
so the registry can take them all without being told any of them.

```python
class DatabaseSkillProvider(SkillProvider):
    supports_discovery = True

    async def discover(self) -> list[str]:
        return [row.skill_id for row in ...]
```

The default raises `DiscoveryNotSupportedError` for the same reason: an empty list would say the
backend is empty, and a caller told that stops looking. `LocalFileSystemSkillProvider` supports
discovery; the HTTP provider does so when the host publishes a root `index.json` listing its
skills.

Register a custom provider:

```python
registry = SkillRegistry()
await registry.register("customer-onboarding", DatabaseSkillProvider(conn))  # conn: your DB handle
```

Register everything a provider holds:

```python
skill_ids = await registry.register_all(DatabaseSkillProvider(conn))
```

Register multiple providers at once:

```python
registry = SkillRegistry()
await registry.register([
    ("customer-onboarding", DatabaseSkillProvider(conn)),
    ("incident-response", LocalFileSystemSkillProvider(path)),
])
```

All three are atomic - if any skill fails validation, none are registered, and the error names
every skill that failed rather than only the first.

### Testing a provider

An ABC enforces that five methods exist and nothing about what they do. The requirements that
actually matter are the ones it cannot express: that an unknown skill ID raises
`SkillNotFoundError` rather than returning `{}`, that `../../etc/passwd` is refused rather than
resolved, and that a provider advertising `supports_resource_listing` can actually list.

`agentskills-testing` turns those into tests you inherit:

```bash
pip install agentskills-testing
```

```python
import pytest

from agentskills_testing import ProviderConformanceSuite


class TestDatabaseProvider(ProviderConformanceSuite):
    @pytest.fixture
    def provider(self):
        return DatabaseSkillProvider(conn)
```

The fixture must expose one skill laid out per the documented contract — the package README lists
it, and every name and byte string is exported as a constant so you can build the fixture from
them rather than from copied literals. Both built-in providers are tested this way.

Traversal assertions are not opt-out. Size limits live in a separate `ContentLimitConformanceSuite`,
because an in-memory provider has no external source to bound — but any provider reading bytes it
did not author should pass it.

The same package ships `InMemorySkillProvider`, a real provider backed by a dict, for testing code
that *consumes* skills. Prefer it to an `AsyncMock`: a mock agrees with whatever the test asserts,
including the assertions that are wrong.

```python
from agentskills_testing import InMemorySkillProvider, build_skill

provider = InMemorySkillProvider({"incident-response": build_skill("incident-response")})
```

See the [package README](packages/testing/agentskills-testing/README.md) for the full fixture
contract and the pytest fixtures it registers.

## Error Handling

Failures are typed so that a caller can tell "this will never work" from "try again later":

| Exception | Meaning |
| --- | --- |
| `SkillNotFoundError` | The skill does not exist. Retrying will not help. |
| `ResourceNotFoundError` | The skill exists; that reference, script, or asset does not. |
| `SkillUnavailableError` | The backend is temporarily unable to answer — a `5xx`, a timeout, a rate limit. Carries `retry_after` when the server advised one. |
| `ResourceListingNotSupportedError` | This provider cannot enumerate resources. Not the same as having none. |
| `DiscoveryNotSupportedError` | This provider cannot enumerate the skills it holds. Not the same as holding none. |

All of them derive from `AgentSkillsError`.

```python
import asyncio
from agentskills_core import SkillNotFoundError, SkillUnavailableError

try:
    body = await registry.get_skill("incident-response").get_body()
except SkillNotFoundError:
    ...                                   # a real 404 — surface it
except SkillUnavailableError as exc:
    await asyncio.sleep(exc.retry_after or 5.0)
```

The HTTP provider already retries transient failures with bounded, jittered backoff and honours
`Retry-After`, so a `SkillUnavailableError` means retrying did not help.

## Logging

Everything logs under a single `agentskills` namespace, so one call turns on the whole SDK:

```python
import logging

logging.getLogger("agentskills").setLevel(logging.DEBUG)
```

Sub-loggers follow the package layout — `agentskills.http.static`, `agentskills.core.registry` —
so you can raise the level on one provider alone. Only a `NullHandler` is attached by default; the
SDK never configures handlers or touches the root logger.

`DEBUG` covers fetches, cache hits, and parses. `INFO` records registration outcomes. `WARNING`
means degraded but recovered, such as a retry after a `503`. There is deliberately no `ERROR`
level: failures raise, and logging them as well would report the same event twice.

URLs are redacted before they are logged or embedded in exceptions, so query strings — SAS tokens,
signed-URL signatures — do not reach your logs or your tracebacks. Headers are never logged.

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

The SDK includes built-in protections: input validation, TLS enforcement options, response size limits, path-traversal guards, credential redaction in logs and tracebacks, and safe XML generation. See each package's README for provider-specific security controls.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on setup, code style, testing, and pull requests.

## License

MIT
