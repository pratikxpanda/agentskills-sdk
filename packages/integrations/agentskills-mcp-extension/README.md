---
title: agentskills-mcp-extension
description: Native MCP Skills publication and origin-preserving client helpers.
---

Publish and consume the official MCP Skills extension with immutable, lossless resources.

## Native Skills Only

The native Skills API requires MCP SDK `>=2.2,<3`. It serves the official
`io.modelcontextprotocol/skills` extension on protocol `2026-07-28` through
`skills/list`, `skills/get`, and canonical `skill://` resources. Clients on older
protocol revisions see the same `skill://` files as ordinary resources and cannot
call the Skills methods. See the
[breaking-change guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/docs/mcp-migration.md).

## Install

```bash
pip install "agentskills-mcp-extension[fs]"
```

The `[http]` extra adds the HTTP provider. Publisher verification needs
`agentskills-core[verification]` and OpenTelemetry export needs
`agentskills-core[telemetry]`. Use an isolated server environment
when a host framework pins a different MCP SDK version.

## Serve a Folder

Prepare `skills/incident-response/SKILL.md` with valid `name` and `description` frontmatter.
The [filesystem guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/providers/agentskills-fs/README.md#usage)
includes a complete sample skill. The Python example publishes that folder over stdio:

```python
import asyncio
from pathlib import Path

from agentskills_core import Skill
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_mcp_extension import create_mcp_server

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

Save the configuration example below as `server.json` and prepare its filesystem skill folder.
Run the client in the environment where this package and the filesystem provider are installed.
This example uses the official SDK to start a stdio subprocess, create a session, and close it
when finished. `McpSkillsClient` wraps that session and leaves transport ownership with the host:

```python
import asyncio
import os
import sys

from mcp import Client, StdioServerParameters

from agentskills_mcp_extension import McpSkillsClient


async def main() -> None:
  parameters = StdioServerParameters(
    command=sys.executable,
    args=["-m", "agentskills_mcp_extension", "--config", "server.json"],
    env={"PYTHONPATH": os.environ.get("PYTHONPATH", "")},
  )
  async with Client(parameters) as connection:
    client = McpSkillsClient(connection.session, origin="incident-runbooks")
    skills = await client.list_skills()
    if not skills:
      print("No skills published")
      return
    skill = await client.get_skill(skills[0].identity.uri)
    print(await client.read_resource(skill, skill.identity.uri))


asyncio.run(main())
```

The example forwards `PYTHONPATH` so a subprocess can find checkout-based packages. With the
package installed in the selected Python environment, that `env` argument can be omitted.

References retain both the supplied origin identity and canonical `skill://` URI. Reads verify
the manifest's size and SHA-256 digest. The client does not implement `SkillProvider` or insert
remote content into a `SkillRegistry`, since registration validates by reading bodies eagerly.
It also keeps no shared response cache, so separate server origins remain isolated.

To compose two sources, keep both SDK `Client` connections open using the pattern above and
pass them to this helper. The caller creates and closes the connections:

```python
from mcp import Client

from agentskills_mcp_extension import McpSkillReference, McpSkillsCollection, McpSkillsClient


async def collect_skills(runbooks: Client, security: Client) -> list[McpSkillReference]:
    catalog = McpSkillsCollection([
        McpSkillsClient(runbooks.session, origin="incident-runbooks"),
        McpSkillsClient(security.session, origin="security-guides"),
    ])
    return await catalog.list_skills()
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

Set `"skill_prompt_shortcuts": true` in server config to enable the same prompt. The host
remains responsible for prompt approval and whether the returned skill content is used.

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
python -m agentskills_mcp_extension --config server.json --check
python -m agentskills_mcp_extension --config server.json
python -m agentskills_mcp_extension --config server.json --transport streamable-http
```

Starting with v0.9, this distribution does not install a console command. The module entry point
selects the installed interpreter explicitly. For the unified console command, install
`agentskills-tools[serve]` and use:

```bash
agentskills serve --config server.json --check
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

### Additional Providers in v0.9

Config-driven publication also accepts `git`, `azure-blob`, `azure-files`, and `oci`.
Install the selected provider alongside this integration or `agentskills-tools[serve]`.
The integration adds no automatic dependencies on these providers. Tools already depends on
filesystem and Git. HTTP, Azure, and OCI source packages remain separate installs:

| Provider | Install | Required options |
| --- | --- | --- |
| `git` | `pip install agentskills-git` | `repository`, `ref`, `cache_dir` |
| `azure-blob` | `pip install "agentskills-azure[blob]"` | `account_url`, `container_name` |
| `azure-files` | `pip install "agentskills-azure[files]"` | `account_url`, `share_name`, `token_intent: "backup"` |
| `oci` | `pip install agentskills-oci` | `repository` |

Git also accepts `subdirectory`, `refresh`, `max_cache_bytes`, and `max_total_cache_bytes`.
The Git executable must be on `PATH`. Azure options include `prefix` and `max_file_bytes`.
Azure Files additionally accepts `max_files` and `max_depth`. Both Azure providers use the
default async Azure credential chain. Azure Files backup intent bypasses file ACLs and requires
an authorized Azure RBAC role. It is never enabled implicitly.

OCI accepts `insecure`, `tls_verify`, `auth_backend`, `max_files`, `max_file_bytes`, and
`max_total_bytes`. TLS verification stays enabled by default, and ORAS handles registry
authentication. The registry must contain the artifact format described in the
[OCI provider guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/providers/agentskills-oci/README.md).

These four providers reject unknown options, runtime `client` or `credential` objects, and
incorrect JSON types before construction. Use JSON booleans and numbers, not quoted strings.
Environment substitution produces strings, so reserve `${VAR}` placeholders for string options.
Provider-owned network clients and credentials are closed after snapshot capture or failure.
Git retains its existing cache-lease lifetime behavior. No provider executes skill scripts.

For example, after preparing a Git repository containing `skills/incident-response/SKILL.md`:

```json
{
  "name": "Git Runbooks",
  "skills": [
    {
      "id": "incident-response",
      "provider": "git",
      "options": {
        "repository": "https://github.com/example/runbooks.git",
        "ref": "main",
        "cache_dir": ".cache/skills",
        "subdirectory": "skills"
      }
    }
  ]
}
```

Replace the repository, ref, subdirectory, and skill ID with your source. Paths retain their
current-working-directory semantics, not the configuration file's directory. The CLI captures
the configured source once. Programmatic refresh requires keeping provider clients open.

The package-specific `--check` option verifies local construction, manifests, and provider
readiness without listening. It does not certify transport, authentication, or host behavior.

## Client Support and Boundaries

Tests exercise MCP 2.2.0 `Client` in-process, over stdio, and over real loopback
Streamable HTTP. CI also checks mcpc 0.7.0 discovery, aliases, pagination, and exact
resource bytes. Use SDK 2 `Client` for extension negotiation, not its older
`ClientSession` compatibility API. Ordinary tools/resources connectivity does not
establish Skills support.

| Client | Evidence | Boundary |
| --- | --- | --- |
| MCP Python SDK 2.2.0 `Client` | Source tests exercise native discovery, lookup, composition, stdio, and loopback HTTP. The documentation check executes the client example above. | Minimum supported SDK. No host activation or model calls. |
| Resolved supported Python SDK, currently 2.3.0 | Clean installed-wheel jobs run native client/server regressions and both CLI preflight modes. | Results apply to the resolved version, not all future 2.x releases. |
| mcpc 0.7.0 | The dedicated SDK-floor CI job tests pagination, direct lookup, aliases, and exact original resource bytes. | Third-party native Skills client, not a framework lifecycle adapter. |

Local secure-HTTP tests also cover accepted initialization and rejection of missing, invalid,
expired, wrong-audience, and insufficient-scope credentials, plus invalid host/origin headers.
Their in-process transport and controlled verifier do not certify a TLS gateway or identity service.

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
