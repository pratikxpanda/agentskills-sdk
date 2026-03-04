# agentskills-agentframework

[![PyPI](https://img.shields.io/pypi/v/agentskills-agentframework)](https://pypi.org/project/agentskills-agentframework/)
[![Python 3.12+](https://img.shields.io/pypi/pyversions/agentskills-agentframework)](https://pypi.org/project/agentskills-agentframework/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> Microsoft Agent Framework integration for the [Agent Skills SDK](../../../README.md) - turn a skill registry into Agent Framework tools.

Generates a set of [Microsoft Agent Framework](https://pypi.org/project/agent-framework/) `FunctionTool` instances from a `SkillRegistry`, ready to be passed to any Agent Framework agent.

## Installation

```bash
pip install agentskills-agentframework
```

Requires Python 3.12+. Installs `agentskills-core` and `agent-framework` as dependencies.

> **Note:** `agent-framework` is currently a pre-release dependency (`>=1.0.0b1`). The constraint will be updated once a stable release is published.

## Usage

### With `AgentSkillsContextProvider` (recommended)

Use `AgentSkillsContextProvider` to automatically inject the skills catalog and tool usage instructions into the agent context each turn. Pass your domain-specific instructions directly to `Agent` and let the context provider handle the skills context:

```python
from agent_framework import Agent
from agent_framework.azure import AzureOpenAIChatClient
from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_agentframework import get_tools, AgentSkillsContextProvider

# Set up registry
provider = LocalFileSystemSkillProvider(Path("./skills"))
registry = SkillRegistry()
await registry.register("incident-response", provider)

client = AzureOpenAIChatClient(
    deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
)
agent = Agent(
    client=client,
    instructions="You are an SRE assistant.",  # domain instructions only
    tools=get_tools(registry),
    ai_context_providers=[AgentSkillsContextProvider(registry)],
)
```

> **Note:** `get_tools(registry)` still needs to be passed via `Agent(tools=...)` separately. `AgentSkillsContextProvider` handles context injection only (catalog and usage instructions); it does not register the tools.

### Manual system prompt (alternative)

```python
from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_agentframework import get_tools, get_tools_usage_instructions

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

Pass `tools` to your Agent Framework agent and inject `system_prompt` into the `instructions`. The catalog tells the agent *what* skills exist; the usage instructions tell it *how* to use the tools.

## Generated Tools

| Tool | Parameters | Description |
| --- | --- | --- |
| `get_skill_metadata` | `skill_id` | Get structured metadata (name, description, etc.) |
| `get_skill_body` | `skill_id` | Load the full markdown instructions |
| `get_skill_reference` | `skill_id`, `name` | Read a reference document |
| `get_skill_script` | `skill_id`, `name` | Read a script |
| `get_skill_asset` | `skill_id`, `name` | Read an asset |

All tools are async-compatible (`FunctionTool` with `@tool` decorator).

## API

### `get_tools(registry: SkillRegistry) -> list[FunctionTool]`

Returns a list of Agent Framework function tools bound to the given registry.

### `get_tools_usage_instructions() -> str`

Returns a markdown string explaining the progressive-disclosure workflow - read metadata, then body, then fetch resources on demand. Designed for system-prompt injection alongside the skill catalog.

### `AgentSkillsContextProvider(registry, *, source_id=None)`

A :class:`~agent_framework.BaseContextProvider` that automatically injects the skills catalog (XML format) and tool usage instructions into the agent's context before each LLM invocation. The catalog is fetched once per session and cached to avoid redundant calls on every turn.

## Example

See [examples/agent-framework/](../../../examples/agent-framework/) for full working demos.

## Error Handling

| Scenario | Exception |
| --- | --- |
| Skill not found in registry | `SkillNotFoundError` |
| Resource not found in skill | `ResourceNotFoundError` |
| Provider errors (HTTP, filesystem) | `AgentSkillsError` |

All exceptions inherit from `AgentSkillsError` (from `agentskills-core`).

> **Note:** Binary content (scripts, assets, references) is decoded as UTF-8 with `errors="replace"`. Non-decodable bytes are replaced with the Unicode replacement character (�).

## License

MIT
