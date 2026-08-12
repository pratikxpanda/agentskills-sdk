# Agent Skills SDK

A Python SDK for discovering, retrieving, and serving
[Agent Skills](https://agentskills.io) to LLM agents.

## What this site covers

- How to integrate skills into agent frameworks
- Provider and registry concepts behind progressive disclosure
- Per-package API reference generated from docstrings
- Project roadmap and architecture decisions (ADRs)

## Install

Pick one provider plus one integration:

```bash
pip install agentskills-fs agentskills-langchain
```

Or install the authoring CLI:

```bash
pip install agentskills-cli
```

## Quick start

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
