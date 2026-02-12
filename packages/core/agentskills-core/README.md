# agentskills-core

[![PyPI](https://img.shields.io/pypi/v/agentskills-core)](https://pypi.org/project/agentskills-core/)
[![Python 3.12+](https://img.shields.io/pypi/pyversions/agentskills-core)](https://pypi.org/project/agentskills-core/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> Core abstractions for the [Agent Skills SDK](../../README.md) — provider interface, registry, validation, and skill model.

This package provides the foundational building blocks for working with the [Agent Skills](https://agentskills.io) format. It is **storage-agnostic** — concrete providers (filesystem, HTTP, database, etc.) live in separate packages.

## Installation

```bash
pip install agentskills-core
```

Requires Python 3.12+.

## What's Included

| Export | Description |
| --- | --- |
| `SkillProvider` | Abstract base class that every skill backend must implement |
| `Skill` | Lightweight runtime handle to a single registered skill |
| `SkillRegistry` | Unified index with explicit registration and catalog builder |
| `validate_skill` | Validates a skill against the Agent Skills specification |
| `split_frontmatter` | Parses YAML frontmatter from `SKILL.md` content |
| `AgentSkillsError` | Base exception for all library errors |
| `SkillNotFoundError` | Raised when a skill does not exist |
| `ResourceNotFoundError` | Raised when a resource within a skill does not exist |

## Usage

### Registering Skills

```python
from agentskills_core import SkillRegistry

registry = SkillRegistry()
await registry.register("incident-response", provider)  # validates on registration
```

Or register multiple skills at once:

```python
await registry.register([
    ("incident-response", fs_provider),
    ("api-style-guide", http_provider),
])
```

Batch registration is atomic — if any skill fails validation, none are registered.

### Accessing Skills

```python
skill = registry.get_skill("incident-response")
meta = await skill.get_metadata()       # YAML frontmatter as dict
body = await skill.get_body()           # Markdown instructions
script = await skill.get_script("run.sh")
```

### Building a Catalog

Generate a catalog string for system-prompt injection:

```python
xml_catalog = await registry.get_skills_catalog(format="xml")       # <available_skills> XML
md_catalog = await registry.get_skills_catalog(format="markdown")   # Markdown list
```

### Implementing a Custom Provider

```python
from agentskills_core import SkillProvider

class DatabaseSkillProvider(SkillProvider):
    async def get_metadata(self, skill_id: str) -> dict: ...
    async def get_body(self, skill_id: str) -> str: ...
    async def get_script(self, skill_id: str, name: str) -> bytes: ...
    async def get_asset(self, skill_id: str, name: str) -> bytes: ...
    async def get_reference(self, skill_id: str, name: str) -> bytes: ...
```

All methods are `async` so implementations backed by network I/O can be non-blocking.

## License

MIT
