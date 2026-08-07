# Getting Started

## Install what you need

The SDK is split into focused packages.

- `agentskills-core` for registry and validation
- One provider (`agentskills-fs` or `agentskills-http`)
- One integration (`agentskills-langchain`, `agentskills-agentframework`, or `agentskills-mcp-server`)

Example:

```bash
pip install agentskills-fs agentskills-langchain
```

## Register skills

```python
from pathlib import Path

from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider

registry = SkillRegistry()
await registry.register_all(LocalFileSystemSkillProvider(Path("./skills")))
```

## Inject the catalog

```python
catalog = await registry.get_skills_catalog(format="xml")
```

The catalog is what the agent sees on every turn. Full skill bodies and resources
are fetched only on demand through tools.

## Author and validate skills

```bash
pip install agentskills-cli
agentskills init incident-response --path ./skills
agentskills validate ./skills
agentskills lint ./skills
```

For integration-specific examples, see each package page in the site navigation.
