---
title: Agent Skills MCP Server
description: Serve the official MCP Skills extension with immutable, lossless resources.
---

## Native Skills Only

The v0.7 development line requires MCP SDK `>=2.2,<3`. It serves the official
`io.modelcontextprotocol/skills` extension on protocol `2026-07-28` through
`skills/list`, `skills/get`, and canonical `skill://` resources.

Legacy tools, `skills://` catalogs, the Agent Framework bridge and extra, and
MCP 1.x support are removed. See the
[breaking-change guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/docs/mcp-migration.md).
v0.7 is not yet released. Install the development checkout until publication.

## Install

The release install is `pip install 'agentskills-mcp-server[fs]>=0.7,<0.8'`.
For development, install the local core, filesystem, and MCP packages together:

```bash
python -m pip install ./packages/core/agentskills-core ./packages/providers/agentskills-fs ./packages/integrations/agentskills-mcp-server
```

The `[http]` extra adds the HTTP provider. Use an isolated server environment
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

`create_mcp_server` is now async. `create_native_mcp_server` names the same
factory. Both accept a `SkillRegistry` or a sequence of raw `Skill` handles.
Raw handles avoid imposing registry-specific parsing restrictions before native
publication. Discovery is metadata-only, including for a single skill.

The factory captures complete immutable file sets before serving. It preserves
original `SKILL.md` bytes, frontmatter, supporting directories, and binary files.
Each manifest contains raw-byte SHA-256 digests and sizes. Restart to refresh.
Server-provided hashes establish consistency, not publisher identity or safety.
Programmatic callers own provider cleanup after capture.

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
The CLI closes owned provider clients after capture, including on failure.

| Field | Default | Meaning |
| --- | --- | --- |
| `name` | Required | Server display name |
| `skills` | Required, nonempty | IDs, provider types, and constructor options |
| `instructions` | `null` | Optional server-level instructions |
| `mode` | `native` | Only `native` is accepted. Remove `legacy` configs |
| `skill_paths` | `{}` | Registry ID to canonical publication path |
| `listed_skill_ids` | `null` | Optional listing subset, not authorization |
| `page_size` | `100` | Maximum entries per discovery page |
| `max_skills` | `128` | Publication skill-count ceiling |
| `max_total_bytes` | `67108864` | Total captured source byte ceiling |

Filesystem options include `root` and `max_file_bytes`. HTTP options include
`base_url`, `headers`, `params`, `file_manifest`, `resource_manifest`, and
`max_response_bytes`. HTTP native publication requires `file_manifest: true` and
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

The former LangChain and Agent Framework examples used removed tools. They are
not v0.7 migration recipes. There is no claim of verified native framework
activation parity. Hosts own selection, manifest verification, origin visibility,
per-skill consent, context injection, session tracking, image rendering, and
execution policy. Resource reads never execute scripts or grant `allowed-tools`.

Production HTTP deployments must supply TLS, MCP authorization, audience isolation,
and appropriate origin/host validation. Do not pass client bearer tokens to upstream
providers. Local tests are not production deployment certification.

## Benchmarks

The [benchmark guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/docs/mcp-benchmarks.md)
describes native discovery and progressive reads over bounded synthetic catalogs.
It does not measure model quality or production network performance.