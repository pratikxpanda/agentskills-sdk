---
title: Agent Skills SDK
description: Python packages for sourcing, managing, and distributing Agent Skills.
---

[![CI](https://github.com/pratikxpanda/agentskills-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/pratikxpanda/agentskills-sdk/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A596%25-brightgreen.svg)](https://github.com/pratikxpanda/agentskills-sdk/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/downloads/)

> A Python SDK for discovering, retrieving, and serving [Agent Skills](https://agentskills.io) to LLM agents.

**Agent Skills** is an [open format](https://agentskills.io/specification) for giving AI agents new capabilities and expertise. Originally developed by Anthropic, the format is now supported by Claude Code, Cursor, GitHub, VS Code, Gemini CLI, and many others.

Read skills from local or remote sources through a common Python API. Use them directly in your
application, or distribute them to compatible hosts through the optional MCP extension.

> **Note:** Requires Python 3.12 or newer. Tested against 3.12, 3.13, and 3.14.

---

## Packages

All packages are versioned together. Badges reflect published PyPI releases and may lag this branch.

| Package | Description | Version | Downloads |
| --- | --- | --- | --- |
| [`agentskills-core`](packages/core/agentskills-core/README.md) | Registry, provider interface, spec validation, immutable snapshots, and trust policies. | [![PyPI](https://img.shields.io/pypi/v/agentskills-core?label=)](https://pypi.org/project/agentskills-core/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-core?label=)](https://pepy.tech/project/agentskills-core) |
| [`agentskills-adapters`](packages/adapters/agentskills-adapters/README.md) | **Adapter**: import AGENTS.md, Copilot instructions, Cursor rules, and Claude skills as native Skill objects. | [![PyPI](https://img.shields.io/pypi/v/agentskills-adapters?label=)](https://pypi.org/project/agentskills-adapters/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-adapters?label=)](https://pepy.tech/project/agentskills-adapters) |
| [`agentskills-fs`](packages/providers/agentskills-fs/README.md) | **Provider**: read skills from a local directory. | [![PyPI](https://img.shields.io/pypi/v/agentskills-fs?label=)](https://pypi.org/project/agentskills-fs/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-fs?label=)](https://pepy.tech/project/agentskills-fs) |
| [`agentskills-git`](packages/providers/agentskills-git/README.md) | **Provider**: resolve Git refs to immutable commits and read skills from a bounded local cache. | [![PyPI](https://img.shields.io/pypi/v/agentskills-git?label=)](https://pypi.org/project/agentskills-git/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-git?label=)](https://pepy.tech/project/agentskills-git) |
| [`agentskills-http`](packages/providers/agentskills-http/README.md) | **Provider**: read skills from a static HTTP server or CDN. | [![PyPI](https://img.shields.io/pypi/v/agentskills-http?label=)](https://pypi.org/project/agentskills-http/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-http?label=)](https://pepy.tech/project/agentskills-http) |
| [`agentskills-azure`](packages/providers/agentskills-azure/README.md) | **Provider**: Azure Blob Storage and Azure Files SMB shares through the `[blob]` and `[files]` extras. | [![PyPI](https://img.shields.io/pypi/v/agentskills-azure?label=)](https://pypi.org/project/agentskills-azure/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-azure?label=)](https://pepy.tech/project/agentskills-azure) |
| [`agentskills-oci`](packages/providers/agentskills-oci/README.md) | **Provider**: fetch skill files on demand from OCI artifacts and verify their digests. | [![PyPI](https://img.shields.io/pypi/v/agentskills-oci?label=)](https://pypi.org/project/agentskills-oci/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-oci?label=)](https://pepy.tech/project/agentskills-oci) |
| [`agentskills-mcp-extension`](packages/integrations/agentskills-mcp-extension/README.md) | **MCP integration**: publish native Skills, consume remote skills, and compose clients across origins. | [![PyPI](https://img.shields.io/pypi/v/agentskills-mcp-extension?label=)](https://pypi.org/project/agentskills-mcp-extension/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-mcp-extension?label=)](https://pepy.tech/project/agentskills-mcp-extension) |
| [`agentskills-retrieval`](packages/retrieval/agentskills-retrieval/README.md) | **Selection**: rank skills for a query with BM25 or embedding-based retrieval. | [![PyPI](https://img.shields.io/pypi/v/agentskills-retrieval?label=)](https://pypi.org/project/agentskills-retrieval/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-retrieval?label=)](https://pepy.tech/project/agentskills-retrieval) |
| [`agentskills-tools`](packages/tools/agentskills-tools/README.md) | **Tooling**: scaffold, validate, lint, inspect, evaluate, lock, and serve skills. | [![PyPI](https://img.shields.io/pypi/v/agentskills-tools?label=)](https://pypi.org/project/agentskills-tools/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-tools?label=)](https://pepy.tech/project/agentskills-tools) |
| [`agentskills-testing`](packages/testing/agentskills-testing/README.md) | **Tooling**: provider conformance checks, pytest fixtures, and an in-memory provider. | [![PyPI](https://img.shields.io/pypi/v/agentskills-testing?label=)](https://pypi.org/project/agentskills-testing/) | [![Downloads](https://img.shields.io/pepy/dt/agentskills-testing?label=)](https://pepy.tech/project/agentskills-testing) |

## How It Works

The SDK separates skill sources from how applications consume them:

1. Providers read skill content from the filesystem, Git, HTTP, Azure, OCI, or your own backend.
  Each provider implements the same interface, so application code can change sources without
  changing how it reads a skill.
2. Core provides `Skill` and `SkillRegistry` for registration, validation, and access to metadata,
  instructions, and supporting files. Python applications can use these APIs directly.
3. The optional MCP extension is a distribution layer. It publishes provider-backed skills to
  remote MCP hosts and supplies clients for reading skills from other servers.

Providers and core work without MCP. Your application decides which skill to select, when to
load its content, and whether to use it. The SDK does not inject prompts or execute skill scripts.

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
description: Triage and mitigate production incidents.
---

# Incident Response

Check service health, identify the affected deployment, and assess customer impact.
```

The `description` is part of discovery metadata. It helps hosts select a skill before loading
its body. Describe the situations where the skill applies.

See [examples/skills/incident-response/](examples/skills/incident-response/) for a complete skill
with references, scripts, and assets.

## Quick Start

Install core and the filesystem provider. MCP is not required for this example:

```bash
pip install agentskills-core agentskills-fs
```

Create `my-skills/incident-response/SKILL.md` with the content shown above, then run:

```python
import asyncio
from pathlib import Path

from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider


async def main() -> None:
    provider = LocalFileSystemSkillProvider(Path("my-skills"))
    registry = SkillRegistry()
    await registry.register_all(provider)

    print(await registry.get_skills_catalog(format="xml"))
    skill = registry.get_skill("incident-response")
    print(await skill.get_body())


asyncio.run(main())
```

Registration validates the skill. The example prints its catalog metadata and reads its body
through the common core API. It does not start a server or call a model.

## Documentation

Full guides and API docs are published at:

- <https://pratikxpanda.github.io/agentskills-sdk/>

The site includes package-by-package API reference generated from docstrings,
plus roadmap and ADR pages.

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

## Security

Agent Skills are equivalent to executable prompt instructions. Only load skills
from sources you trust. Optional publisher verification, content policy, and
public-network-only HTTP defaults are described in the
[trust and operability guide](docs/trust-and-operability.md). See
[SECURITY.md](SECURITY.md) for vulnerability reporting and threat-model notes.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, style, and PR expectations.

## License

MIT
