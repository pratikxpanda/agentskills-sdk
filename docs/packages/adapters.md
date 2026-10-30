---
title: Format Adapters
description: Convert supported instruction files into imported skill handles and native Markdown.
---

Convert common agent instruction formats into an `ImportedSkill` containing a runtime `Skill`,
the source path, and rendered `SKILL.md` text.

```bash
pip install agentskills-adapters
```

Supported sources include `AGENTS.md`, Copilot instructions, Cursor `.mdc` rules,
and Claude-style folders containing `SKILL.md`. The
[package guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/adapters/agentskills-adapters/README.md#import-a-file)
shows reading the result and writing a reviewed native skill folder. Supporting files are not
copied automatically. CLI conversion is documented in the [tools guide](tools.md).

::: agentskills_adapters
    options:
      show_root_heading: true
