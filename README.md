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
| [`agentskills-adapters`](packages/adapters/agentskills-adapters/README.md) | **Adapter** - import AGENTS.md, Copilot instructions, Cursor rules, and Claude skills as native Skill objects. | [![PyPI](https://img.shields.io/pypi/v/agentskills-adapters?label=)](https://pypi.org/project/agentskills-adapters/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-adapters?label=)](https://pepy.tech/project/agentskills-adapters) |
| [`agentskills-fs`](packages/providers/agentskills-fs/README.md) | **Provider** - read skills from a local directory. | [![PyPI](https://img.shields.io/pypi/v/agentskills-fs?label=)](https://pypi.org/project/agentskills-fs/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-fs?label=)](https://pepy.tech/project/agentskills-fs) |
| [`agentskills-http`](packages/providers/agentskills-http/README.md) | **Provider** - read skills from a static HTTP server or CDN. | [![PyPI](https://img.shields.io/pypi/v/agentskills-http?label=)](https://pypi.org/project/agentskills-http/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-http?label=)](https://pepy.tech/project/agentskills-http) |
| [`agentskills-langchain`](packages/integrations/agentskills-langchain/README.md) | **Integration** - expose skills to a LangChain agent as tools. | [![PyPI](https://img.shields.io/pypi/v/agentskills-langchain?label=)](https://pypi.org/project/agentskills-langchain/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-langchain?label=)](https://pepy.tech/project/agentskills-langchain) |
| [`agentskills-agentframework`](packages/integrations/agentskills-agentframework/README.md) | **Integration** - expose skills to a Microsoft Agent Framework agent, injected automatically through the agent lifecycle. | [![PyPI](https://img.shields.io/pypi/v/agentskills-agentframework?label=)](https://pypi.org/project/agentskills-agentframework/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-agentframework?label=)](https://pepy.tech/project/agentskills-agentframework) |
| [`agentskills-mcp-server`](packages/integrations/agentskills-mcp-server/README.md) | **Integration** - serve skills over the Model Context Protocol to any MCP client, such as Claude Desktop, VS Code, or Cursor. | [![PyPI](https://img.shields.io/pypi/v/agentskills-mcp-server?label=)](https://pypi.org/project/agentskills-mcp-server/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-mcp-server?label=)](https://pepy.tech/project/agentskills-mcp-server) |
| [`agentskills-tools`](packages/tools/agentskills-tools/README.md) | **Tooling** - the `agentskills` command: scaffold, validate, lint, and inspect skills. | [![PyPI](https://img.shields.io/pypi/v/agentskills-tools?label=)](https://pypi.org/project/agentskills-tools/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-tools?label=)](https://pepy.tech/project/agentskills-tools) |
| [`agentskills-testing`](packages/testing/agentskills-testing/README.md) | **Tooling** - the provider conformance suite and an in-memory provider, for anyone writing a provider or testing against one. | [![PyPI](https://img.shields.io/pypi/v/agentskills-testing?label=)](https://pypi.org/project/agentskills-testing/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-testing?label=)](https://pepy.tech/project/agentskills-testing) |

**Which do I need?** One provider for wherever your skills live, plus the integration for your
agent framework. Both pull in `agentskills-core`, so a LangChain app reading skills from disk
needs only:

```bash
pip install agentskills-fs agentskills-langchain
```

If you *write* skills rather than consume them, you want `agentskills-tools` instead.

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

    # What the agent sees on every turn: names, descriptions, and where each
    # skill does and does not apply. Nothing more.
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

A description says what a skill is for, and nothing about where it stops. Two optional
frontmatter fields say the rest:

```yaml
---
name: incident-response
description: Triage and mitigate production incidents.
when_to_use:
  - A production service is degraded or down
when_not_to_use:
  - Debugging a failing test locally
---
```

Both are capped at five entries of 200 characters, because they ride in the catalog and are
charged on every turn. Pass `selection_hints=False` to leave them out.

## Documentation

Full guides and API docs are published at:

- <https://pratikxpanda.github.io/agentskills-sdk/>

The site includes package-by-package API reference generated from docstrings,
plus roadmap and ADR pages.

## Integrations

- LangChain: [examples/langchain/](examples/langchain/)
- Microsoft Agent Framework: [examples/agent-framework/](examples/agent-framework/)
- MCP server: [packages/integrations/agentskills-mcp-server/README.md](packages/integrations/agentskills-mcp-server/README.md)

## Command Line

For skill authoring:

```bash
pip install agentskills-tools
agentskills validate ./skills
agentskills lint ./skills
agentskills inspect ./skills --cost
```

See [packages/tools/agentskills-tools/README.md](packages/tools/agentskills-tools/README.md)
for full command and JSON schema details.

## GitHub Action

If your skills live in GitHub, use the validation action:

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

## Custom providers and testing

- Provider contract and exceptions: `agentskills-core`
- Conformance suite and in-memory provider: `agentskills-testing`
- Development/test commands: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

## Security

Agent Skills are equivalent to executable prompt instructions. Only load skills
from sources you trust. See [SECURITY.md](SECURITY.md) for vulnerability
reporting and threat-model notes.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, style, and PR expectations.

## License

MIT
