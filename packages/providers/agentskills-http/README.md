# agentskills-http

[![PyPI](https://img.shields.io/pypi/v/agentskills-http)](https://pypi.org/project/agentskills-http/)
[![Python 3.12 | 3.13](https://img.shields.io/pypi/pyversions/agentskills-http)](https://pypi.org/project/agentskills-http/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> HTTP static-file skill provider for the [Agent Skills SDK](https://github.com/pratikxpanda/agentskills-sdk).

Serves [Agent Skills](https://agentskills.io) from any static HTTP file host - S3, Azure Blob, CDN, GitHub Pages, Nginx, etc. Expects the same directory-tree layout as the filesystem provider, served over HTTP.

## Installation

```bash
pip install agentskills-http
```

Requires Python 3.12 or newer. Installs `agentskills-core`, `httpx`, and `pyyaml` as dependencies.

## Expected URL Layout

```text
https://cdn.example.com/skills/
├── incident-response/
│   ├── SKILL.md
│   ├── references/severity-levels.md
│   ├── scripts/page-oncall.sh
│   └── assets/flowchart.mermaid
└── another-skill/
    └── SKILL.md
```

## Usage

```python
from agentskills_core import SkillRegistry
from agentskills_http import HTTPStaticFileSkillProvider

async with HTTPStaticFileSkillProvider("https://cdn.example.com/skills") as provider:
    registry = SkillRegistry()
    await registry.register("incident-response", provider)

    skill = registry.get_skill("incident-response")
    meta = await skill.get_metadata()
    body = await skill.get_body()
```

### Custom Headers

Pass authentication or other headers:

```python
from agentskills_http import HTTPStaticFileSkillProvider

provider = HTTPStaticFileSkillProvider(
    "https://cdn.example.com/skills",
    headers={"Authorization": "Bearer <token>"},
)
```

### Bring Your Own Client

Supply a pre-configured `httpx.AsyncClient` for full control over timeouts, proxies, etc.:

```python
import httpx
from agentskills_http import HTTPStaticFileSkillProvider

client = httpx.AsyncClient(timeout=30, headers={"Authorization": "Bearer <token>"})
provider = HTTPStaticFileSkillProvider("https://cdn.example.com/skills", client=client)
# caller is responsible for closing the client
```

> **Note:** `client` and `headers` are mutually exclusive. Configure headers on the client directly when providing your own.

## API

### `HTTPStaticFileSkillProvider(base_url, *, client=None, headers=None, params=None, require_tls=False, max_response_bytes=10_485_760, revalidate=False)`

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `base_url` | `str` | - | Root URL where the skill tree is hosted |
| `client` | `AsyncClient \| None` | `None` | Pre-configured httpx client (caller manages lifecycle) |
| `headers` | `dict \| None` | `None` | Extra headers sent with every request |
| `params` | `dict \| None` | `None` | Query parameters appended to every request |
| `require_tls` | `bool` | `False` | Reject `http://` URLs with `ValueError` |
| `max_response_bytes` | `int` | `10_485_760` | Maximum allowed response size in bytes |
| `revalidate` | `bool` | `False` | Re-check cached `SKILL.md` on every access with `If-None-Match` / `If-Modified-Since` |
| `resource_manifest` | `bool` | `False` | Enable `list_resources()` by reading a per-skill `index.json` |
| `skill_manifest` | `bool` | `False` | Enable `discover()` by reading a root `index.json` |
| `timeout` | `float` | `30.0` | Request timeout in seconds (ignored when you supply `client`) |
| `max_retries` | `int` | `2` | Retries after the initial attempt, for retryable failures only |
| `retry_backoff` | `float` | `0.5` | Base delay in seconds for exponential backoff |
| `max_retry_delay` | `float` | `30.0` | Ceiling on any single backoff sleep |

> **Note:** `client` and `headers`/`params` are mutually exclusive. Configure headers and params on the client directly when providing your own.

| Method | Returns | Description |
| --- | --- | --- |
| `get_metadata(skill_id)` | `dict[str, Any]` | Parsed YAML frontmatter from `SKILL.md` |
| `get_body(skill_id)` | `str` | Markdown body after the frontmatter |
| `get_script(skill_id, name)` | `bytes` | Raw script content |
| `get_asset(skill_id, name)` | `bytes` | Raw asset content |
| `get_reference(skill_id, name)` | `bytes` | Raw reference content |
| `list_resources(skill_id)` | `dict[str, list[str]]` | Resource names from `index.json` (requires `resource_manifest=True`) |
| `discover()` | `list[str]` | Skill IDs from the root `index.json` (requires `skill_manifest=True`) |
| `invalidate(skill_id=None)` | `None` | Drop cached `SKILL.md` content for one skill, or all skills |
| `aclose()` | `None` | Close the HTTP client (if owned by the provider) |

Supports `async with` for automatic cleanup.

## Resource Discovery

A static file host cannot be enumerated: there is no portable directory listing over plain HTTP. By default this provider therefore reports that it *cannot* list resources — `list_resources()` raises `ResourceListingNotSupportedError` — rather than returning an empty mapping that would look like a skill with no resources.

If you control the host, publish a small manifest at `{base_url}/{skill_id}/index.json`:

```json
{
  "references": ["severity-levels.md"],
  "scripts": ["page-oncall.sh"],
  "assets": ["flowchart.mermaid"]
}
```

Then opt in:

```python
provider = HTTPStaticFileSkillProvider(BASE, resource_manifest=True)
listing = await provider.list_resources("incident-response")
```

Missing categories default to empty lists. A manifest is host-supplied data whose entries are later interpolated into URLs, so names failing the identifier-safety check are dropped. If a given skill has no `index.json`, `list_resources()` raises `ResourceListingNotSupportedError` for that skill — again, not an empty result.

## Skill Discovery

The same problem one level up: nothing on a static host says which skills exist. Publish the same
file at the root, listing skills instead of resources:

```json
{ "skills": ["incident-response", "api-style-guide"] }
```

Then opt in and register the whole host at once:

```python
async with HTTPStaticFileSkillProvider(BASE, skill_manifest=True) as provider:
    await registry.register_all(provider)
```

One filename and one shape — an object mapping a category to a list of names — at two depths,
rather than two manifest formats to keep in step. Unsafe and duplicate IDs are dropped as above.
Without `skill_manifest=True`, or when the root publishes no manifest, `discover()` raises
`DiscoveryNotSupportedError`.

## Caching

`SKILL.md` responses are cached per provider instance. Without it a single skill costs up to five round-trips per agent session — twice during registration, once per catalog build, and again on each tool call. Scripts, assets and references are not cached.

By default the cache is served until you call `invalidate()`. If your host serves mutable skills and the process is long-lived, opt into conditional revalidation instead:

```python
provider = HTTPStaticFileSkillProvider(BASE, revalidate=True)
```

That sends `If-None-Match` / `If-Modified-Since` on every access and reuses the cached body on `304`. It costs one cheap round-trip per access, so prefer the default plus an explicit `invalidate()` when you control publishing.

## Error Handling

| Scenario | Exception | Retried |
| --- | --- | --- |
| `404` / `410` on `SKILL.md` | `SkillNotFoundError` | No |
| `404` / `410` on a resource | `ResourceNotFoundError` | No |
| `5xx`, `408`, `425`, `429` | `SkillUnavailableError` | Yes |
| Timeouts, connection and protocol errors | `SkillUnavailableError` | Yes |
| `401` / `403` | `AgentSkillsError` | No |
| Other `4xx`, oversized responses | `AgentSkillsError` | No |

All exceptions inherit from `AgentSkillsError`.

The split between `SkillNotFoundError` and `SkillUnavailableError` is the point of the taxonomy: a `503` means the skill may well exist and the same request could succeed in a moment, whereas a `404` means it is gone. Collapsing both into "not found" turns a retryable blip into a permanent-looking failure, and nothing downstream can tell the difference.

### Retries

Retryable failures are retried with exponential backoff and full jitter:

```python
provider = HTTPStaticFileSkillProvider(
    BASE,
    max_retries=2,          # attempts after the first; 0 disables
    retry_backoff=0.5,      # base delay in seconds
    max_retry_delay=30.0,   # ceiling on any single sleep
)
```

Jitter matters because a registry builds its catalog concurrently — without it, every skill fetch would retry in lockstep and hit the recovering server as one wave.

`Retry-After` is honoured in both the delay-seconds and HTTP-date forms. If the server asks for longer than `max_retry_delay`, the request is **not** retried: blocking a request path for minutes is worse than failing fast. The advised delay is still available to the caller as `SkillUnavailableError.retry_after`, so a scheduler can act on it.

## Security

- **Input validation** - Skill IDs and resource names are validated against a safe-character pattern (`^[a-zA-Z0-9][a-zA-Z0-9._-]*$`) to prevent path-traversal and injection attacks.
- **TLS warnings** - A `UserWarning` is emitted when `base_url` uses unencrypted HTTP. Set `require_tls=True` to reject HTTP URLs entirely.
- **Redirect protection** - The internally-created HTTP client does not follow redirects by default, preventing open-redirect SSRF.
- **Timeouts** - Default 30-second timeout on all HTTP requests. Configure via `timeout`.
- **Response size limits** - Responses exceeding 10 MB (default) are rejected before processing. Configure via `max_response_bytes`.
- **Error-message sanitization** - Messages carry the status code and the path *relative to `base_url`* — never the host, never a query string. The underlying `httpx` exception is deliberately **not** chained (`from None`), because `httpx.HTTPStatusError` renders the full request URL including its query string, which is exactly where SAS tokens and signed-URL signatures live. Chaining it leaked credentials into every traceback.

For the full security policy, see [SECURITY.md](https://github.com/pratikxpanda/agentskills-sdk/blob/main/SECURITY.md).

## Deployment Considerations

- **Rate limiting** - The SDK does not enforce rate limits on MCP tool
  calls or HTTP requests. Deploy behind a reverse proxy or API gateway
  that provides rate limiting in production environments.
- **Credential management** - Do not store secrets (API keys, SAS
  tokens, Authorization headers) in config files committed to version
  control. Use environment variables or a secret manager instead.

## License

MIT
