---
title: Agent Skills SDK
description: Native MCP Skills publication and framework-neutral Python packages.
---

A Python SDK for discovering, retrieving, and serving
[Agent Skills](https://agentskills.io) to LLM agents.

## What this site covers

- Native Skills publication for compatible MCP hosts
- Provider and registry concepts behind progressive disclosure
- Per-package API reference generated from docstrings
- Project roadmap and architecture decisions (ADRs)

## Install

v0.6.0 is released. The v0.7 development line is native-only. Review the
[breaking changes](mcp-migration.md). Install the checkout until v0.7 is published:

```bash
pip install ./packages/core/agentskills-core ./packages/providers/agentskills-fs ./packages/integrations/agentskills-mcp-server
```

Or install the authoring CLI:

```bash
pip install agentskills-tools
```

## Quick start

Publish the sample skills with `python -m agentskills_mcp_server --config
examples/server-fs.json`. A conforming Skills host is required for activation.
The following framework-neutral APIs remain available for custom hosts:

```python
import asyncio
from pathlib import Path

from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider


async def main() -> None:
    registry = SkillRegistry()
    await registry.register_all(LocalFileSystemSkillProvider(Path("my-skills")))

    catalog = await registry.get_skills_catalog(format="xml")
    print(catalog)

    skill = registry.get_skill("incident-response")
    print(await skill.get_body())


asyncio.run(main())
```

Continue with [Getting Started](getting-started.md) and [Concepts](concepts.md).
