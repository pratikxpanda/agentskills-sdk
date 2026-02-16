# agentskills-http

[![PyPI](https://img.shields.io/pypi/v/agentskills-http)](https://pypi.org/project/agentskills-http/)
[![Python 3.12+](https://img.shields.io/pypi/pyversions/agentskills-http)](https://pypi.org/project/agentskills-http/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> HTTP static-file skill provider for the [Agent Skills SDK](../../README.md).

Serves [Agent Skills](https://agentskills.io) from any static HTTP file host — S3, Azure Blob, CDN, GitHub Pages, Nginx, etc. Expects the same directory-tree layout as the filesystem provider, served over HTTP.

## Installation

```bash
pip install agentskills-http
```

Requires Python 3.12+. Installs `agentskills-core`, `httpx`, and `pyyaml` as dependencies.

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
provider = HTTPStaticFileSkillProvider(
    "https://cdn.example.com/skills",
    headers={"Authorization": "Bearer <token>"},
)
```

### Bring Your Own Client

Supply a pre-configured `httpx.AsyncClient` for full control over timeouts, proxies, etc.:

```python
import httpx

client = httpx.AsyncClient(timeout=30, headers={"Authorization": "Bearer <token>"})
provider = HTTPStaticFileSkillProvider("https://cdn.example.com/skills", client=client)
# caller is responsible for closing the client
```

> **Note:** `client` and `headers` are mutually exclusive. Configure headers on the client directly when providing your own.

## API

### `HTTPStaticFileSkillProvider(base_url, *, client=None, headers=None, params=None, require_tls=False, max_response_bytes=10_485_760)`

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `base_url` | `str` | — | Root URL where the skill tree is hosted |
| `client` | `AsyncClient \| None` | `None` | Pre-configured httpx client (caller manages lifecycle) |
| `headers` | `dict \| None` | `None` | Extra headers sent with every request |
| `params` | `dict \| None` | `None` | Query parameters appended to every request |
| `require_tls` | `bool` | `False` | Reject `http://` URLs with `ValueError` |
| `max_response_bytes` | `int` | `10_485_760` | Maximum allowed response size in bytes |

> **Note:** `client` and `headers`/`params` are mutually exclusive. Configure headers and params on the client directly when providing your own.

| Method | Returns | Description |
| --- | --- | --- |
| `get_metadata(skill_id)` | `dict[str, Any]` | Parsed YAML frontmatter from `SKILL.md` |
| `get_body(skill_id)` | `str` | Markdown body after the frontmatter |
| `get_script(skill_id, name)` | `bytes` | Raw script content |
| `get_asset(skill_id, name)` | `bytes` | Raw asset content |
| `get_reference(skill_id, name)` | `bytes` | Raw reference content |
| `aclose()` | `None` | Close the HTTP client (if owned by the provider) |

Supports `async with` for automatic cleanup.

## Error Handling

| Scenario | Exception |
| --- | --- |
| 404 on `SKILL.md` | `SkillNotFoundError` |
| 404 on a resource | `ResourceNotFoundError` |
| Other HTTP errors (500, 403, ...) | `AgentSkillsError` |
| Connection failures | `AgentSkillsError` |

All exceptions inherit from `AgentSkillsError`.

## Security

- **Input validation** — Skill IDs and resource names are validated against a safe-character pattern (`^[a-zA-Z0-9][a-zA-Z0-9._-]*$`) to prevent path-traversal and injection attacks.
- **TLS warnings** — A `UserWarning` is emitted when `base_url` uses unencrypted HTTP. Set `require_tls=True` to reject HTTP URLs entirely.
- **Redirect protection** — The internally-created HTTP client does not follow redirects by default, preventing open-redirect SSRF.
- **Timeouts** — Default 30-second timeout on all HTTP requests.
- **Response size limits** — Responses exceeding 10 MB (default) are rejected before processing. Configure via `max_response_bytes`.
- **Error-message sanitization** — Error messages omit URLs and include only status codes and generic descriptions, preventing internal URL leakage.

For the full security policy, see [SECURITY.md](../../../SECURITY.md).

## Deployment Considerations

- **Rate limiting** — The SDK does not enforce rate limits on MCP tool
  calls or HTTP requests. Deploy behind a reverse proxy or API gateway
  that provides rate limiting in production environments.
- **Credential management** — Do not store secrets (API keys, SAS
  tokens, Authorization headers) in config files committed to version
  control. Use environment variables or a secret manager instead.

## License

MIT
