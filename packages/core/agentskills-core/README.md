# agentskills-core

[![PyPI](https://img.shields.io/pypi/v/agentskills-core)](https://pypi.org/project/agentskills-core/)
[![Python 3.12 | 3.13](https://img.shields.io/pypi/pyversions/agentskills-core)](https://pypi.org/project/agentskills-core/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> Core abstractions for the [Agent Skills SDK](https://github.com/pratikxpanda/agentskills-sdk) - provider interface, registry, validation, and skill model.

This package provides the foundational building blocks for working with the [Agent Skills](https://agentskills.io) format. It is **storage-agnostic** - concrete providers (filesystem, HTTP, database, etc.) live in separate packages.

## Installation

```bash
pip install agentskills-core
```

Requires Python 3.12 or newer.

## What's Included

| Export | Description |
| --- | --- |
| `SkillProvider` | Abstract base class that every skill backend must implement |
| `Skill` | Lightweight runtime handle to a single registered skill |
| `SkillRegistry` | Unified index with explicit registration and catalog builder |
| `validate_skill` | Validates a skill against the Agent Skills specification |
| `validate_version` | Validates an optional semver `version` frontmatter value |
| `get_logger` | Returns a logger in the shared `agentskills.*` namespace |
| `redact_url` | Strips credentials from a URL before it is logged or raised |
| `split_frontmatter` | Parses YAML frontmatter from `SKILL.md` content |
| `split_sections` | Splits a skill body into flat, addressable `Section` values |
| `outline_of` | Builds a `SkillOutline` of a body's sections and their cost |
| `SkillOutline` | A body's section keys, token costs, and fetch guidance |
| `estimate_tokens` | Cheap heuristic token count (4 characters per token) |
| `resolve_fast_path` | Decides whether a one-skill registry should skip discovery entirely |
| `FastPath` | The resolved decision: which skill, its body, and the prompt to inject |
| `AgentSkillsError` | Base exception for all library errors |
| `SkillNotFoundError` | Raised when a skill does not exist |
| `SectionNotFoundError` | Raised when a body has no section with the given key |
| `ResourceNotFoundError` | Raised when a resource within a skill does not exist |
| `ResourceListingNotSupportedError` | Raised when a provider cannot enumerate a skill's resources |
| `DiscoveryNotSupportedError` | Raised when a provider cannot enumerate the skills it holds |
| `SkillUnavailableError` | Raised when a backend is unreachable or fails transiently |

## Usage

### Registering Skills

```python
from agentskills_core import SkillRegistry

# provider: any SkillProvider - agentskills-fs, agentskills-http, or your own
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

Or let the provider name them, when it can enumerate itself:

```python
skill_ids = await registry.register_all(fs_provider)
```

`register_all()` raises `DiscoveryNotSupportedError` for backends that cannot be enumerated;
check `provider.supports_discovery` first if you do not know which kind you have.

All three are atomic - if any skill fails validation, none are registered, and the error names
every skill that failed rather than only the first.

### Accessing Skills

```python
skill = registry.get_skill("incident-response")
meta = await skill.get_metadata()       # YAML frontmatter as dict
body = await skill.get_body()           # Markdown instructions
script = await skill.get_script("run.sh")
```

### Reading Part of a Body

A long body is otherwise all-or-nothing. Ask for its outline first, then fetch only the
section you need:

```python
outline = await registry.get_skill_outline("incident-response")
print(outline.render())     # agent-facing text: keys, token costs, and advice

if not outline.whole_body_is_cheaper:
    text = await registry.get_skill_section("incident-response", "roles")
```

Keys are slugified headings, with `-2`, `-3` appended on collision. Addressing is **flat**:
a section covers its own text up to the next heading of any level, so fetching a parent does
not include its subsections. An unknown key raises `SectionNotFoundError`, whose message
lists the keys that do exist.

`outline.whole_body_is_cheaper` is true below `WHOLE_BODY_CHEAPER_TOKENS` (1000), where the
tool call and outline tokens cost more than they save; `render()` says so in words, so agents
reading only the rendered text still get the guidance.

### Building a Catalog

Generate a catalog string for system-prompt injection:

```python
xml_catalog = await registry.get_skills_catalog(format="xml")       # <available_skills> XML
md_catalog = await registry.get_skills_catalog(format="markdown")   # Markdown list
```

Metadata for every registered skill is fetched concurrently, which matters when providers are network-backed. Bound the fan-out at construction time:

```python
registry = SkillRegistry(catalog_concurrency=4)   # default: 8
```

### Selection Metadata

`description` says what a skill is for. `when_to_use` and `when_not_to_use` say where it applies and where it stops:

```yaml
---
name: incident-response
description: Triage and mitigate production incidents.
when_to_use:
  - A production service is degraded or down
when_not_to_use:
  - Debugging a failing test locally
---
```

Both are optional lists of at most five non-empty strings of at most 200 characters each. They render next to the description in both formats and are omitted entirely when absent, so a skill that declares neither renders exactly as it did before this existed:

```xml
<skill>
  <name>incident-response</name>
  <description>Triage and mitigate production incidents.</description>
  <when_to_use>
    <case>A production service is degraded or down</case>
  </when_to_use>
  <when_not_to_use>
    <case>Debugging a failing test locally</case>
  </when_not_to_use>
</skill>
```

The limits exist because these fields are charged on every turn for every registered skill, the same as the description. Pass `selection_hints=False` to trade the accuracy back for tokens.

### Narrowing and Capping the Catalog

The catalog goes into every system prompt on every turn, so its size is a fixed cost per request. Five keyword arguments control it:

```python
catalog = await registry.get_skills_catalog(
    tags=["incident"],              # any-of match, case-insensitive
    include=["runbook-a"],          # allow-list of skill IDs
    exclude=["deprecated-runbook"], # deny-list, applied last
    max_chars=8000,                 # hard ceiling on the returned string
    selection_hints=False,          # drop when_to_use / when_not_to_use
)
```

`include` and `exclude` match skill IDs and run **before** any metadata is fetched, so narrowing a large registry costs proportionally fewer provider round-trips. `tags` needs metadata and runs after.

The two ID filters are deliberately asymmetric about IDs that are not registered. `include` raises `SkillNotFoundError`, because an allow-list naming a skill that does not exist silently costs the agent a capability. `exclude` ignores them, because a deny-list is meant to outlive the thing it denies.

Tags are read from the spec's free-form `metadata` mapping, not from a new top-level field:

```yaml
---
name: incident-response
description: Diagnose and mitigate a production incident.
metadata:
  tags: [incident, sev1]
---
```

`max_chars` drops whole entries from the end until the result fits, so the output stays well-formed and the same arguments always produce the same catalog. Truncation is never silent — the XML root gains `truncated`, `shown` and `total` attributes, and the Markdown gains a closing note:

```xml
<available_skills truncated="true" shown="12" total="40">
```

A catalog that shrinks without saying so makes agent behaviour non-reproducible. Roughly four characters per token is the usual estimate; the ceiling is in characters so that core needs no tokenizer.

There is no catalog cache today. If one is added, its key must cover the format and every filter argument above.

### Single-Skill Fast Path

A catalog exists to let a model choose. With one skill there is nothing to choose, so the whole discovery apparatus — a catalog listing one entry, eight tool definitions, a block of usage instructions, and a model round trip while the agent calls `get_skill_body` and waits — is spent reaching content there was never a choice about.

```python
from agentskills_core import resolve_fast_path

fast_path = await resolve_fast_path(registry)
if fast_path is not None:
    print(fast_path.prompt)      # the body, inlined, instead of a catalog
    print(fast_path.skill_id)    # which skill was chosen
    print(fast_path.tokens)      # what it costs, by the counter the outline uses
```

Pass the result to any integration's `fast_path=` argument. It returns `None` — meaning "use the normal catalog path" — unless the effective skill set is exactly one and its body fits under the ceiling.

Resolution lives here rather than in each integration because the decision is identical everywhere, and because the ceiling is the part that has to be tuned: one knob is tunable, three that must be kept in step are not.

**Narrowing counts.** `include=` applies an effective set, so a registry of fifty narrowed to one by a selector takes the same path as a registry that only ever held one:

```python
selection = await selector.select(registry, query)          # agentskills-retrieval
fast_path = await resolve_fast_path(registry, include=selection.skill_ids)
```

**The ceiling is not a guess.** The normal path pays the catalog and usage instructions every turn (~500 tokens together) and the body once. The fast path pays a ~200-token wrapper and the body every turn. Over `T` turns the fast path wins while `body × (T − 1) < 300 × T`:

| Conversation length | Fast path wins while body is |
| --- | --- |
| 1 turn | any size |
| 2 turns | < 612 tokens |
| 3 turns | < 459 tokens |
| 10 turns | < 340 tokens |
| 100 turns | < 309 tokens |

An integration knows the body size but not how many turns the conversation will run, so `DEFAULT_FAST_PATH_MAX_TOKENS` is 300 — the value that needs no assumption about the latter. Raise it with `max_tokens=` if you know your conversations are short. Both refusals, too many skills and too large a body, are logged; silently switching prompt shape based on content size is how token bills become impossible to explain.

**Resource tools stay.** `FAST_PATH_DROPPED_TOOLS` covers only the four that would re-fetch inlined content (`get_skill_metadata`, `get_skill_body`, `get_skill_outline`, `get_skill_section`). References, scripts and assets are still genuinely progressive — a skill carrying a 2 MB dataset must not have it inlined because the skill count happened to be one.

### Skill Versions (optional, non-spec)

A skill may declare a `version` in its frontmatter. It is optional — skills without one remain
valid and behave exactly as before:

```yaml
---
name: incident-response
description: Standard operating procedures for production incident management.
version: "1.2.0"
---
```

When present, the value must be a **quoted** [semver](https://semver.org) string. Registration
fails otherwise:

```python
from agentskills_core import validate_version

validate_version("2.1.0-rc.1")   # None
validate_version("1.0")          # "version '1.0' is not valid semver. ..."
validate_version(1.0)            # "version must be a quoted string, got float ..."
```

The quoting requirement is not pedantry: YAML parses an unquoted `1.0` as a float and `2024-01-15`
as a date, so the three most likely authoring mistakes never reach the validator as strings. The
error message names the cause rather than reporting a bare type mismatch.

Versions appear in both catalog formats when set, and are omitted entirely when not — unversioned
skills cost no extra prompt tokens.

> `version` is **not** part of the upstream Agent Skills specification. It is supported here
> because consumers cannot pin, compare, or detect drift without it. The field is being raised
> upstream rather than kept as a permanent proprietary extension.

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

### Resource Discovery (optional capability)

Some backends can enumerate a skill's resources; a static file host generally cannot. `list_resources()` is therefore an *optional* capability, paired with a declared flag ([ADR 0002](../../../docs/adr/0002-optional-provider-capabilities.md)):

```python
class DatabaseSkillProvider(SkillProvider):
    supports_resource_listing = True

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        return {"references": [...], "scripts": [...], "assets": [...]}
```

The default implementation **raises** `ResourceListingNotSupportedError` rather than returning `{}`. "I cannot enumerate this skill" and "this skill has no resources" are different facts, and conflating them would silently hide resources from the agent.

Consumers should branch on the capability, not guess:

```python
from agentskills_core import ResourceListingNotSupportedError

try:
    listing = await skill.list_resources()
except ResourceListingNotSupportedError:
    listing = None   # fall back to names mentioned in the skill body
```

Providers that support listing always return all three keys — `references`, `scripts`, `assets` — with empty lists for unused categories, so callers need no key checks.

### Skill Discovery (optional capability)

The same pattern one level up: `discover()` returns the IDs of every skill the backend holds, so `register_all()` can take them all without being told any of them.

```python
class DatabaseSkillProvider(SkillProvider):
    supports_discovery = True

    async def discover(self) -> list[str]:
        return [row.skill_id for row in ...]
```

The default raises `DiscoveryNotSupportedError`, for the same reason as above — a caller told the backend is empty stops looking, while a caller told it cannot be enumerated falls back to explicit registration:

```python
if provider.supports_discovery:
    await registry.register_all(provider)
else:
    await registry.register("incident-response", provider)
```

Discovery does not validate. An ID it returns can still fail `validate_skill()`, which is what `register_all()` reports on.

### Encoding Resources for Tool Output

Resources are `bytes`, but tool interfaces return text. `encode_resource_content()` is the shared conversion used by every integration, so behaviour cannot drift between them:

```python
from agentskills_core import encode_resource_content

text = encode_resource_content("architecture.png", raw_bytes)
```

Valid UTF-8 passes through unchanged. Anything else returns a JSON envelope carrying the media type and base64 content, so binaries are never silently corrupted. Binaries above `max_inline_binary_bytes` (default 64 KiB) are described but not inlined.

### Classifying Resources for Native Delivery

An envelope is the right answer for an opaque binary and the wrong one for a diagram — the model gets a wall of base64 where a picture was. `classify_resource()` decides which is which, once, so the three integrations cannot drift on what counts as an image:

```python
from agentskills_core import classify_resource

media = classify_resource("architecture.png", raw_bytes)
media.media_type  # "image/png"
media.renderable  # True
```

Detection reads the leading bytes first and the name second: a name is a claim, bytes are evidence. A `.png` holding a ZIP is not renderable, and a real PNG called `.dat` is.

`renderable` is `True` only for PNG, JPEG, GIF and WebP within `max_inline_image_bytes`. PDF is excluded because some models read it and others reject it, and guessing wrong is an API error rather than a worse answer. SVG is excluded because it is text the model can already reason about; rasterising it would trade that for something it can only look at.

Images get their own ceiling, `DEFAULT_MAX_INLINE_IMAGE_BYTES` (5 MiB), rather than sharing the 64 KiB binary cap. The binary cap tracks tokens, because base64 in a text field is billed per byte; a native image is billed by tile count, so the same ceiling would have turned nearly every real screenshot into a stub saying it was too large. 5 MiB is the lowest per-image limit among the major vision APIs.

Integrations use this behind an opt-in `vision=True` flag — see [ADR 0009](https://github.com/pratikxpanda/agentskills-sdk/blob/main/docs/adr/0009-native-image-content.md). When `renderable` is `False` the caller falls back to `encode_resource_content()`, which is always safe.

### Logging

Every package in the SDK logs under one `agentskills.*` namespace, and the library attaches only a `NullHandler` — output is entirely the host's decision:

```python
import logging

logging.getLogger("agentskills").setLevel(logging.DEBUG)
```

`DEBUG` covers fetch, parse and cache events; `INFO` covers registration outcomes; `WARNING` covers degraded-but-recovered behaviour such as a retried HTTP request. There is no `ERROR` level: anything that fails raises instead, so failures are never reported twice.

Custom providers should join the namespace rather than creating their own. Pass `__name__` — the distribution prefix is rewritten, so `agentskills_http.static` logs as `agentskills.http.static`:

```python
from agentskills_core import get_logger, redact_url

_logger = get_logger(__name__)
_logger.debug("GET %s", redact_url(url, relative_to=base_url))
```

`redact_url()` drops the query string, fragment and userinfo, which is where credentials actually live — SAS tokens, signed-URL signatures, basic-auth passwords. With `relative_to` it drops the scheme and host as well, leaving only the path beneath that base.

## Security

- **Frontmatter size limits** - `split_frontmatter()` rejects YAML frontmatter blocks exceeding 256 KB (`MAX_FRONTMATTER_BYTES`) to prevent memory-exhaustion attacks.
- **Metadata validation** - `validate_skill()` checks types of known optional fields (`license`, `compatibility`, `metadata`, `allowed-tools`, `version`) and logs warnings for unknown top-level metadata keys.
- **Safe XML generation** - `get_skills_catalog(format="xml")` uses `xml.etree.ElementTree` for catalog generation, avoiding XML injection via string concatenation.
- **Credential-safe logging** - the SDK never logs request headers, and URLs pass through `redact_url()` before reaching a log record or an exception message.

For the full security policy, see [SECURITY.md](https://github.com/pratikxpanda/agentskills-sdk/blob/main/SECURITY.md).

## License

MIT
