# agentskills-langchain

[![PyPI](https://img.shields.io/pypi/v/agentskills-langchain)](https://pypi.org/project/agentskills-langchain/)
[![Python 3.12 | 3.13](https://img.shields.io/pypi/pyversions/agentskills-langchain)](https://pypi.org/project/agentskills-langchain/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> LangChain integration for the [Agent Skills SDK](https://github.com/pratikxpanda/agentskills-sdk) - turn a skill registry into LangChain tools.

Generates a set of [LangChain](https://python.langchain.com/) `StructuredTool` instances from a `SkillRegistry`, ready to be passed to any LangChain agent.

## Installation

```bash
pip install agentskills-langchain
```

Requires Python 3.12 or newer. Installs `agentskills-core` and `langchain-core` as dependencies.

## Usage

```python
from pathlib import Path

from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_langchain import get_tools, get_tools_usage_instructions

# Set up registry
provider = LocalFileSystemSkillProvider(Path("./skills"))
registry = SkillRegistry()
await registry.register("incident-response", provider)

# Build tools + system prompt
tools = get_tools(registry)
catalog = await registry.get_skills_catalog(format="xml")
instructions = get_tools_usage_instructions()
system_prompt = f"{catalog}\n\n{instructions}"
```

Pass `tools` to your LangChain agent and inject `system_prompt` into the system message. The catalog tells the agent *what* skills exist; the usage instructions tell it *how* to use the tools.

## Generated Tools

| Tool | Parameters | Description |
| --- | --- | --- |
| `get_skill_metadata` | `skill_id` | Get structured metadata (name, description, etc.) |
| `get_skill_body` | `skill_id` | Load the full markdown instructions |
| `get_skill_reference` | `skill_id`, `name` | Read a reference document |
| `get_skill_script` | `skill_id`, `name` | Read a script |
| `get_skill_asset` | `skill_id`, `name` | Read an asset |

All tools are async-compatible (`StructuredTool` with `coroutine`).

## API

### `get_tools(registry: SkillRegistry, *, max_inline_binary_bytes: int = 65536) -> list[StructuredTool]`

Returns a list of LangChain structured tools bound to the given registry.

### `get_tools_usage_instructions() -> str`

Returns a markdown string explaining the progressive-disclosure workflow - read metadata, then body, then fetch resources on demand. Designed for system-prompt injection alongside the skill catalog.

## Example

See [examples/langchain/](https://github.com/pratikxpanda/agentskills-sdk/tree/main/examples/langchain) for a full working demo.

## Error Handling

| Scenario | Exception |
| --- | --- |
| Skill not found in registry | `SkillNotFoundError` |
| Resource not found in skill | `ResourceNotFoundError` |
| Provider errors (HTTP, filesystem) | `AgentSkillsError` |

All exceptions inherit from `AgentSkillsError` (from `agentskills-core`).

## Binary Resources

Skill resources may be arbitrary files. Valid UTF-8 is returned as-is; anything else is returned as a JSON envelope, so a binary payload is never silently mangled into replacement characters:

```json
{
  "name": "architecture.png",
  "media_type": "image/png",
  "size_bytes": 20481,
  "encoding": "base64",
  "content": "iVBORw0KGgo..."
}
```

Base64 costs roughly 1.37 characters per byte, so binaries above 64 KiB are described rather than inlined - `"encoding": "none"` plus a `note` explaining the omission. Adjust the ceiling with:

```python
tools = get_tools(registry, max_inline_binary_bytes=256 * 1024)
```

## License

MIT
