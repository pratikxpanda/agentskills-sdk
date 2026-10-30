---
title: agentskills-mcp-server
description: Native MCP Skills publication and origin-preserving client helpers.
---

Serve the official MCP Skills extension with immutable, lossless resources.

## Native Skills Only

The native Skills API requires MCP SDK `>=2.2,<3`. It serves the official
`io.modelcontextprotocol/skills` extension on protocol `2026-07-28` through
`skills/list`, `skills/get`, and canonical `skill://` resources. Clients on older
protocol revisions see the same `skill://` files as ordinary resources and cannot
call the Skills methods. See the
[breaking-change guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/docs/mcp-migration.md).

## Install

```bash
pip install "agentskills-mcp-server[fs]"
```

The `[http]` extra adds the HTTP provider. Publisher verification needs
`agentskills-core[verification]` and OpenTelemetry export needs
`agentskills-core[telemetry]`. Use an isolated server environment
when a host framework pins a different MCP SDK version.

## Serve a Folder

```python
import asyncio
from pathlib import Path

from agentskills_core import Skill
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_mcp_server import create_mcp_server

provider = LocalFileSystemSkillProvider(Path("./skills"))
server = asyncio.run(create_mcp_server([Skill("incident-response", provider)]))
server.run(transport="stdio")
```

`create_mcp_server` is async and accepts a `SkillRegistry` or a sequence of raw
`Skill` handles. Raw handles avoid imposing registry-specific parsing restrictions
before publication. Discovery is metadata-only, including for a single skill.

The factory captures complete immutable file sets before serving. It preserves
original `SKILL.md` bytes, frontmatter, supporting directories, and binary files.
Each manifest contains raw-byte SHA-256 digests and sizes. A file whose bytes are
valid UTF-8 without NUL is read as `text` and every other file as `blob`. Both
forms return the exact captured bytes. Programmatic servers
support `await server.refresh()` and `server.health()`.
Server-provided hashes establish consistency, not publisher identity or safety.
Programmatic callers own provider cleanup and must keep providers open for refresh.
Optional `publication_policy` verifies detached signatures, pins content, and
applies reject/redact/annotate hooks before manifests are generated. See the
[trust and operability guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/docs/trust-and-operability.md)
for publisher configuration, token limits, verified stale policy, telemetry,
and authenticated remote HTTP deployment.

## Consume Skills

Wrap an initialized official MCP client session to list manifests without reading skill bodies.
Keep the session, transport, credentials, selection, and approval under host control:

```python
from agentskills_mcp_server import McpSkillsClient

client = McpSkillsClient(session, origin="incident-runbooks")
skills = await client.list_skills()
skill = await client.get_skill(skills[0].identity.uri)
body_resource = next(
  item for item in skill.manifest["resources"] if item["uri"] == skill.identity.uri
)
body = await client.read_resource(skill, body_resource["uri"])
```

References retain both the supplied origin identity and canonical `skill://` URI. Reads verify
the manifest's size and SHA-256 digest. The client does not implement `SkillProvider` or insert
remote content into a `SkillRegistry`, since registration validates by reading bodies eagerly.
It also keeps no shared response cache, so separate server origins remain isolated.

Compose multiple sources on the client side when several servers use the same skill URI:

```python
from agentskills_mcp_server import McpSkillsCollection, McpSkillsClient

catalog = McpSkillsCollection([
  McpSkillsClient(runbooks_session, origin="incident-runbooks"),
  McpSkillsClient(security_session, origin="security-guides"),
])
references = await catalog.list_skills()
```

Identity remains `(origin, URI)`. The collection does not rehost or forward content, which avoids
loops and keeps approval and session state with the application.

## Prompt Shortcut

Hosts that support MCP prompts can opt in to one user-invoked `use-skill` prompt. It requires the
canonical `skill://` URI and reads the current published snapshot when requested. It is disabled
by default and does not grant tool permissions:

```python
server = await create_mcp_server(skills, skill_prompt_shortcuts=True)
```

Set `"skill_prompt_shortcuts": true` in server config or pass `--skill-prompts` to
`agentskills serve`. The host remains responsible for prompt approval and whether the returned
skill content is used.

## Configuration

```json
{
  "name": "Skills Server",
  "skills": [
    {"id": "incident-response", "provider": "fs", "options": {"root": "./skills"}}
  ]
}
```

```bash
python -m agentskills_mcp_server --config server.json --check
python -m agentskills_mcp_server --config server.json
python -m agentskills_mcp_server --config server.json --transport streamable-http
```

JSON and YAML are supported. `${VAR}` placeholders resolve from the environment.
Unknown top-level keys are rejected. The CLI closes owned provider clients after
capture, including on failure.

| Field | Default | Meaning |
| --- | --- | --- |
| `name` | Required | Server display name |
| `skills` | Required, nonempty | IDs, provider types, and constructor options |
| `instructions` | `null` | Optional server-level instructions |
| `skill_paths` | `{}` | Registry ID to canonical publication path |
| `listed_skill_ids` | `null` | Optional listing subset, not authorization |
| `page_size` | `100` | Maximum entries per discovery page |
| `max_skills` | `128` | Publication skill-count ceiling |
| `max_total_bytes` | `67108864` | Total captured source byte ceiling |

Filesystem options include `root` and `max_file_bytes`. HTTP options include
`base_url`, `headers`, `params`, `file_manifest`, `resource_manifest`, and
`max_response_bytes`. HTTP native publication requires `file_manifest: true` and
a public destination by default. Internal destinations require explicit
`allow_private_network: true`. Redirects are always rejected. Configure
`require_tls`, `timeout`, and retry limits as needed. Publication requires
a complete per-skill file index. See the
[HTTP provider](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/providers/agentskills-http/README.md).

The extension enforces 512 files and 16 MiB per skill. Directory reads are not
advertised. Nested skills require explicit publication and separate host approval.
Listed subsets never restrict direct lookup of a published skill. Supply only
skills authorized for the server audience.

The tools CLI uses native publication by default:

```bash
agentskills inspect ./skills --native
agentskills serve ./skills --check
agentskills serve ./skills --transport stdio
```

`--check` verifies local construction, manifests, and provider readiness without
listening. It does not certify transport, authentication, or host behavior.

## Client Support and Boundaries

Tests exercise MCP 2.2.0 `Client` in-process, over stdio, and over real loopback
Streamable HTTP. CI also checks mcpc 0.7.0 discovery, aliases, pagination, and exact
resource bytes. Use SDK 2 `Client` for extension negotiation, not its older
`ClientSession` compatibility API. Ordinary tools/resources connectivity does not
establish Skills support.

Hosts own selection, manifest verification, origin visibility,
per-skill consent, context injection, session tracking, image rendering, and
execution policy. Resource reads never execute scripts or grant `allowed-tools`.

Production HTTP deployments must supply TLS, MCP authorization, audience isolation,
and appropriate origin/host validation. Do not pass client bearer tokens to upstream
providers. Local tests are not production deployment certification.

## Benchmarks

The [benchmark guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/docs/mcp-benchmarks.md)
describes native discovery and progressive reads over bounded synthetic catalogs.
It does not measure model quality or production network performance.
