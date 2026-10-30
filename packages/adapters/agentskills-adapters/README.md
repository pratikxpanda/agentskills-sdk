---
title: agentskills-adapters
description: Convert supported instruction files into native skill content for review and migration.
---

Convert supported instruction files into an `ImportedSkill` containing a runtime `Skill`,
the source path, and rendered `SKILL.md` text. Conversion does not execute the instructions.

## Install

```bash
pip install agentskills-adapters
```

Requires Python 3.12 or newer. It installs `agentskills-core` and PyYAML.

## Import a File

Create an `AGENTS.md` in your working directory, then run:

```python
import asyncio

from agentskills_adapters import adapt_path, discover_sources


async def main() -> None:
    imported = adapt_path("AGENTS.md", name="team-instructions")
    print(imported.source)
    print(await imported.skill.get_metadata())
    print(await imported.skill.get_body())
    print(imported.skill_md)

    for source in discover_sources("."):
        print(source)


asyncio.run(main())
```

`adapt_path` reads one path. `discover_sources` only enumerates supported sources beneath a
root. Review that list before importing a large directory. Use `name` and `description`
arguments to override generated metadata.

## Supported Sources

- `AGENTS.md` and `.github/copilot-instructions.md`
- Cursor `.cursor/rules/*.mdc` files, preserving `globs` in `metadata`
- Claude-style skill folders containing `SKILL.md`

Formats without a description receive an explicit synthesized description such as
`Imported instructions from AGENTS.md.` They are never emitted with a blank catalog entry.

## Write a Native Skill

The result is in memory until you write it. This example creates a native skill folder:

```python
from pathlib import Path

from agentskills_adapters import adapt_path

imported = adapt_path("AGENTS.md", name="team-instructions")
destination = Path("skills") / imported.skill.get_id()
destination.mkdir(parents=True, exist_ok=True)
(destination / "SKILL.md").write_text(imported.skill_md, encoding="utf-8")
```

Review an existing destination before running this example because `write_text` overwrites it.
Supporting files are not copied automatically. The in-memory imported provider does not expose
complete file access for native MCP publication. To publish, review the rendered folder and
its supporting files, then use a filesystem provider.

For file conversion through the authoring CLI, see the
[tools guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/tools/agentskills-tools/README.md#init).
