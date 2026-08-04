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
| `AgentSkillsError` | Base exception for all library errors |
| `SkillNotFoundError` | Raised when a skill does not exist |
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

### Narrowing and Capping the Catalog

The catalog goes into every system prompt on every turn, so its size is a fixed cost per request. Four keyword arguments control it:

```python
catalog = await registry.get_skills_catalog(
    tags=["incident"],              # any-of match, case-insensitive
    include=["runbook-a"],          # allow-list of skill IDs
    exclude=["deprecated-runbook"], # deny-list, applied last
    max_chars=8000,                 # hard ceiling on the returned string
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
