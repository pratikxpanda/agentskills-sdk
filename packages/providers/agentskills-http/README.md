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

### `HTTPStaticFileSkillProvider(base_url, *, client=None, headers=None)`

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

## License

MIT
