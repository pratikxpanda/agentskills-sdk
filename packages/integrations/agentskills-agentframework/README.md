# agentskills-agentframework

[![PyPI](https://img.shields.io/pypi/v/agentskills-agentframework)](https://pypi.org/project/agentskills-agentframework/)
[![Python 3.12 | 3.13](https://img.shields.io/pypi/pyversions/agentskills-agentframework)](https://pypi.org/project/agentskills-agentframework/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> Microsoft Agent Framework integration for the [Agent Skills SDK](https://github.com/pratikxpanda/agentskills-sdk) - turn a skill registry into Agent Framework tools.

Generates a set of [Microsoft Agent Framework](https://pypi.org/project/agent-framework/) `FunctionTool` instances from a `SkillRegistry`, ready to be passed to any Agent Framework agent.

## Installation

```bash
pip install agentskills-agentframework
```

Requires Python 3.12 or newer. Installs `agentskills-core` and `agent-framework` as dependencies.

> **Note:** `agent-framework` is currently a pre-release dependency (`>=1.0.0rc3`). The constraint will be updated once a stable release is published.

## Usage

### Context Provider (recommended)

The simplest way to integrate is via `AgentSkillsContextProvider`. It plugs into the Agent Framework lifecycle and automatically injects the skill catalog and tools on every `agent.run()` call — no manual system-prompt assembly required.

```python
from pathlib import Path

from agent_framework import Agent
from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_agentframework import AgentSkillsContextProvider

# Set up registry
provider = LocalFileSystemSkillProvider(Path("./skills"))
registry = SkillRegistry()
await registry.register("incident-response", provider)

# Create context provider
skills_context_provider = AgentSkillsContextProvider(registry)

# Pass it to the agent — catalog + tools are injected automatically
agent = Agent(
    client=client,  # any Agent Framework chat client
    name="SREAssistant",
    instructions="You are an SRE assistant.",
    context_providers=[skills_context_provider],
)
response = await agent.run("What severity is a full DB outage?")
```

> See [examples/agent-framework/](https://github.com/pratikxpanda/agentskills-sdk/tree/main/examples/agent-framework) for full working demos including client setup.

| Parameter | Default | Description |
| --- | --- | --- |
| `skills_instruction_prompt` | Built-in template | Custom prompt template. Must contain `{skills_catalog}` and `{tools_usage_instructions}` placeholders. |
| `skills_catalog_format` | `"xml"` | Skills catalog format — `"xml"` or `"markdown"`. |
| `source_id` | `"agentskills"` | Unique identifier for this provider instance. |
| `cache_prompt` | `True` | Reuse the assembled prompt across runs in a session. Invalidated automatically when the registry's skills or the loaded set change. |
| `prune_loaded_skills` | `True` | Drop catalog entries for skills whose full body the agent has already loaded this session. |
| `fast_path` | `None` | A `FastPath` from `agentskills_core.resolve_fast_path`. Inlines the body of a lone skill and drops the catalog, the usage instructions and the four body-access tools. |

### Session-aware disclosure

The provider keeps per-session bookkeeping in the `state` dict Agent Framework hands to
`before_run()` / `after_run()`, which makes later turns cheaper than the first.

**Caching** stores the assembled prompt so an unchanged turn costs no registry I/O. It does not
save tokens — the same text is still sent. The cache key covers the catalog format, the
registered skills and the loaded set, so registering a skill mid-session is picked up without a
TTL to tune.

**Pruning** is what makes turn N+1 smaller. When `after_run()` sees a `get_skill_body` call, the
skill is recorded as loaded; its full instructions are now in the conversation, so repeating its
catalog entry pays for the same thing twice. Later turns advertise the remaining skills and
replace the pruned entries with a one-line reminder, and the catalog reports the narrowing
(`shown="2" total="3"`) rather than presenting itself as complete.

Deliberate limits:

- Only `get_skill_body` counts as a load. `get_skill_outline` and `get_skill_section` read a
  fragment, and a fragment is not the skill.
- If every registered skill has been loaded, the full catalog is emitted. A catalog saying the
  agent has no skills is worse than a repeated entry.
- If the reminder would cost more than the entries it replaces — possible when skills carry very
  terse metadata — pruning is declined for that turn.
- Pruning assumes the loaded body is still in the conversation. If your host compacts history,
  set `prune_loaded_skills=False`.

The loaded set is published on `context.metadata["agentskills_loaded_skills"]` for other context
providers, and held as a plain sorted list so session state stays JSON-serialisable.

Repeated `before_run()` calls on the same context inject once; the guard is keyed by `source_id`,
so two providers over two registries can still both contribute.

### Single-skill fast path

An agent with one skill pays the whole discovery apparatus — a catalog listing one entry, eight
tool definitions, usage instructions describing a selection workflow, and a model round trip while
it calls `get_skill_body` — to reach content there was never a choice about.

```python
from agentskills_core import resolve_fast_path

fast_path = await resolve_fast_path(registry)
provider = AgentSkillsContextProvider(registry, fast_path=fast_path)
```

`resolve_fast_path` returns `None` unless the effective skill set is exactly one and its body fits
under a token ceiling, and `fast_path=None` is the normal path — so the call above is safe
unconditionally. When it does fire, the body is injected directly, the catalog and usage
instructions are gone, and only the four resource tools are attached. Pass
`include=selection.skill_ids` to resolve against a set narrowed by
[agentskills-retrieval](https://github.com/pratikxpanda/agentskills-sdk/tree/main/packages/retrieval/agentskills-retrieval)
rather than the whole registry.

The ceiling, the arithmetic behind its default, and why resource tools stay are documented in the
[core README](https://github.com/pratikxpanda/agentskills-sdk/tree/main/packages/core/agentskills-core#single-skill-fast-path).
Resolve it again if the registry changes.

### Manual Tools

For full control over system-prompt construction, use `get_tools()` directly:

```python
from pathlib import Path

from agent_framework import Agent
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

# Pass to agent
agent = Agent(
    client=client,  # any Agent Framework chat client
    name="SREAssistant",
    instructions=f"{catalog}\n\n{instructions}",
    tools=tools,
)
```

The catalog tells the agent *what* skills exist; the usage instructions tell it *how* to use the tools.

> See [examples/agent-framework/](https://github.com/pratikxpanda/agentskills-sdk/tree/main/examples/agent-framework) for full working demos including client setup.

## Generated Tools

| Tool | Parameters | Description |
| --- | --- | --- |
| `get_skill_metadata` | `skill_id` | Get structured metadata (name, description, etc.) |
| `get_skill_body` | `skill_id` | Load the full markdown instructions |
| `get_skill_outline` | `skill_id` | List the body's sections, keys and token costs |
| `get_skill_section` | `skill_id`, `key` | Load one section of the body |
| `list_skill_resources` | `skill_id` | List bundled references, scripts and assets |
| `get_skill_reference` | `skill_id`, `name` | Read a reference document |
| `get_skill_script` | `skill_id`, `name` | Read a script |
| `get_skill_asset` | `skill_id`, `name` | Read an asset |

All tools are async-compatible (`FunctionTool` with `@tool` decorator).

`get_skill_outline` exists so a large skill is not all-or-nothing. Its rendered text carries the whole-body cost alongside the per-section costs and says outright when `get_skill_body` is the cheaper call — a section fetch is not free, it costs a tool call and a model turn on top of the outline. Section keys are flat slugs and sections do not nest, so fetching a parent does not include what is indented under it in the outline.

`list_skill_resources` returns a JSON object keyed by resource kind. Not every backend can enumerate resources — a plain static HTTP host cannot. Rather than surfacing an exception, the tool returns `{"supported": false, "note": "..."}` in that case: "this cannot be listed" is something the model can act on by falling back to the names in the skill body, not an error worth retrying.

## API

### `AgentSkillsContextProvider(registry, *, skills_instruction_prompt=None, skills_catalog_format="xml", source_id=None, cache_prompt=True, prune_loaded_skills=True)`

A `ContextProvider` that injects skill catalog + tools into the agent session automatically via `before_run()`. Skips injection when the registry has no skills.

### `get_tools(registry: SkillRegistry, *, max_inline_binary_bytes: int = 65536) -> list[FunctionTool]`

Returns a list of Agent Framework function tools bound to the given registry.

### `get_tools_usage_instructions() -> str`

Returns a markdown string explaining the progressive-disclosure workflow - read metadata, then body, then fetch resources on demand. Designed for system-prompt injection alongside the skill catalog.

## Comparison with Agent Framework's built-in provider

Agent Framework ships its own `FileAgentSkillsProvider`. Both plug into the same lifecycle, but they solve different problems:

| | `FileAgentSkillsProvider` (built-in) | `AgentSkillsContextProvider` (this package) |
| --- | --- | --- |
| **Backends** | Filesystem only | Any `SkillProvider` - filesystem, HTTP, custom |
| **Tool surface** | 2 generic tools (`load_skill`, `read_skill_resource`) | 8 typed tools (metadata, body, outline, section, resources, reference, script, asset) |
| **Resource semantics** | Flat - all resources accessed by path | Typed - the agent knows the category of what it is reading |
| **Discovery / parsing** | Built into the framework | Delegated to `agentskills-core` |
| **Composability** | Single provider | Mix multiple providers in one registry |
| **Setup** | Point at a folder | Register skills explicitly |

If all you need is skills in a local folder, the built-in provider is already installed and is the simpler choice. Reach for this package when skills come from somewhere other than disk, when you need several sources in one catalog, or when you want the agent to distinguish a script from a reference document.

## Example

See [examples/agent-framework/](https://github.com/pratikxpanda/agentskills-sdk/tree/main/examples/agent-framework) for full working demos.

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
