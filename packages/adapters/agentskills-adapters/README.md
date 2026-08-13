# agentskills-adapters

Import common agent instruction formats as ordinary `agentskills-core` `Skill` objects.

```python
from agentskills_adapters import adapt_path, discover_sources

for source in discover_sources("."):
    skill = adapt_path(source)
```

Supported sources:

- `AGENTS.md` and `.github/copilot-instructions.md`
- Cursor `.cursor/rules/*.mdc` files, preserving `globs` in `metadata`
- Claude-style skill folders containing `SKILL.md`

Formats without a description receive an explicit synthesized description such as
`Imported instructions from AGENTS.md.` They are never emitted with a blank catalog entry.

Use `agentskills init --from <path>` to write a native `SKILL.md` for editing and review.
Adapters are a migration path, not a fork of the Agent Skills specification.
