---
title: agentskills-mcp-server
description: MCP tools and resources for Agent Skills registries.
---

[![PyPI](https://img.shields.io/pypi/v/agentskills-mcp-server)](https://pypi.org/project/agentskills-mcp-server/)
[![Python 3.12 | 3.13](https://img.shields.io/pypi/pyversions/agentskills-mcp-server)](https://pypi.org/project/agentskills-mcp-server/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> MCP server integration for the [Agent Skills SDK](https://github.com/pratikxpanda/agentskills-sdk) - expose a skill registry as an MCP server.

Creates a [Model Context Protocol](https://modelcontextprotocol.io/) server from a `SkillRegistry`, exposing skills through ordinary MCP tools and resources. v0.6.0 also provides an opt-in native Skills server backed by immutable file captures.

The MCP server remains maintained. Only `AgentSkillsMcpContextProvider` and the
`[agentframework]` extra are deprecated and maintenance-only in v0.6. Existing
bridge APIs remain available during the migration window. See the
[migration guide and feature-gap matrix](https://github.com/pratikxpanda/agentskills-sdk/blob/main/docs/mcp-migration.md)
for framework-owned replacements and removal gates.

## Installation

```bash
pip install agentskills-mcp-server
```

With provider extras:

```bash
pip install agentskills-mcp-server[fs]    # filesystem provider
pip install agentskills-mcp-server[http]  # HTTP provider
```

With Agent Framework integration:

```bash
pip install agentskills-mcp-server[agentframework]  # MCP context provider for Agent Framework
```

Requires Python 3.12 or newer. Installs `agentskills-core`, `mcp`, and `pydantic` as dependencies.

### MCP SDK Compatibility

v0.6.0 accepts MCP SDK 1.28.1 or newer in the 1.x line, or 2.2.0 or
newer in the 2.x line. SDK 2.0 and 2.1 are excluded. The repository lock keeps
1.29.0, while a separate CI job exercises 2.2.0 and the unlocked job checks the
latest permitted dependencies. Direct server tests and real legacy stdio sessions
cover the same eight tools and three static `skills://` resources.

`create_mcp_server()` returns the installed SDK's server class: `FastMCP` on 1.x
and `MCPServer` on 2.x. SDK-level Python APIs follow that SDK's version. For
example, direct `call_tool()` calls return a tuple on 1.x and `CallToolResult` on
2.x. Protocol clients receive standard MCP results in either case. This support
does not imply that a host supports the Skills extension. Native mode is a separate
opt-in and does not establish host-specific certification.

Agent Framework's upstream MCP client still declares an MCP 1.x constraint. Keep
that client and the existing context-provider bridge in a 1.x environment:

```bash
pip install "agentskills-mcp-server[agentframework]" "mcp>=1.28.1,<2"
```

Run a 2.x server in a separate environment or process when using that client.
Do not force incompatible framework extras into the server environment. The
native integrations and context-provider bridge remain available during the
planned deprecation window.

### Tested Client Matrix

The development checkout was verified with the official Python MCP SDK clients
and mcpc on 2026-10-06. These are protocol and client checks, not model-host
activation or production deployment certifications.

| Server mode and SDK | Client SDK and API | Transport | Verified behavior |
| --- | --- | --- | --- |
| Legacy 1.29.0 | 1.29.0 `ClientSession` | stdio | Eight tools, three static resources, tool errors |
| Legacy 2.2.0 | 2.2.0 `ClientSession` | stdio | Same legacy contract |
| Legacy 2.2.0 | 1.29.0 `ClientSession` | stdio | Same contract across separate environments |
| Legacy 1.29.0 | 2.2.0 `ClientSession` | stdio | Same contract across separate environments |
| Native 2.2.0 | 2.2.0 `Client` | In-process, stdio, loopback HTTP | Native discovery, lookup, and original-byte resources |
| Native 2.2.0 | `@apify/mcpc` 0.7.0 | stdio | Direct lookup before listing, paginated discovery, aliases, exact instructions/reference/binary reads with sizes and SHA-256 digests |
| Native 2.2.0 | 1.29.0 or 2.2.0 `ClientSession` | stdio | Canonical resources only, native discovery rejected with `-32601` |

SDK 2's `ClientSession` is its legacy-protocol compatibility API. Use `Client`
for the native protocol. The HTTP checks use a real listener and both values of
the server's `json_response` option. They verify resource bytes against the source
and advertised size and digest, plus required result/cache fields. They do not
certify remote authentication, TLS, reverse proxies, or a host's approval policy.

The modern-SDK CI job creates an isolated 1.29.0 environment and runs both
mixed-SDK stdio directions. Locally, `AGENTSKILLS_TEST_MCP_SERVER_PYTHON` selects
the legacy server interpreter for `test_config.py -k stdio`, and
`AGENTSKILLS_TEST_NATIVE_MCP_SERVER_PYTHON` selects a 2.2+ native server interpreter.
Without overrides, tests use the current interpreter and skip native publication
when SDK 2.2+ is unavailable. Each interpreter needs this checkout's core, provider,
and MCP packages. The client also needs pytest and pytest-asyncio.

The same CI job installs pinned `@apify/mcpc@0.7.0` and runs the real-client test.
To repeat it locally with Node 22.12 or later and MCP SDK 2.2, set
`AGENTSKILLS_TEST_MCPC` to the installed package's `bin/mcpc` JavaScript entry
point and run `pytest packages/integrations/agentskills-mcp-server/tests/test_config.py -k mcpc`.
The test isolates its session state and closes the session in a cleanup block.
It does not call a model, execute skill scripts, or test remote authentication.

### Discovery and Delivery Benchmarks

The development checkout includes a model-free benchmark for catalogs of 1, 10,
and 100 skills. It records actual request counts, payload sizes, token estimates,
and in-process timings for native Skills and the retained legacy API. Native
publication reads are separated from client delivery, and discovery prefetch is
rejected. See the [benchmark guide and measured trade-offs](https://github.com/pratikxpanda/agentskills-sdk/blob/main/docs/mcp-benchmarks.md).
Synthetic ranking scores are not production accuracy or host certification.

## Native Skills

Install `agentskills-mcp-server>=0.6.0` with `mcp>=2.2,<3`. Released 0.5.0
packages do not contain this API. The native server implements the official
[Skills extension](https://modelcontextprotocol.io/extensions/skills/overview)
against protocol revision `2026-07-28`:

- `server/discover` declares `io.modelcontextprotocol/skills` and resources.
- `skills/list` returns complete manifests with opaque, server-scoped pagination.
- `skills/get` returns the same entry directly by its canonical `SKILL.md` URI.
- `resources/read` returns captured original bytes, including BOMs and line endings.
- Results carry the required result type, cache fields, and SDK-generated metadata.

Native mode does not register legacy tools or inject a catalog. It does not
advertise `directoryRead`. The providers cannot enumerate empty directories, so
the optional directory method is deliberately unavailable.

### Native CLI

```json
{
    "name": "Native Skills",
    "mode": "native",
    "skills": [
        {
            "id": "incident-response",
            "provider": "fs",
            "options": {"root": "./skills"}
        }
    ]
}
```

Run it with `python -m agentskills_mcp_server --config server.json`. Omitted
`mode` retains legacy behavior. HTTP providers require `"file_manifest": true`
and complete per-skill file indexes. The CLI closes its provider clients after
capture. The programmatic builder does not close caller-owned providers.

Check configured providers and publication without starting a listener:

```bash
python -m agentskills_mcp_server --config server.json --check
```

The JSON success report includes the installed MCP SDK version, selected mode,
provider types, skill count, and native client requirements. It excludes provider
options, including credential-bearing URLs. Its `localServerConstruction` scope
does not claim a transport connection, authentication check, or host verification.
Provider reads do occur during preflight. Native mode reads and verifies every
file, while legacy mode validates registration. Provider clients opened by a
preflight are closed before it returns, including when construction fails.

For a filesystem source, the companion tools can inspect canonical manifests and
run the same native builder without a config file:

```bash
agentskills inspect ./skills --native --format json
agentskills serve ./skills --native --check
```

Those tools default to a 16 MiB per-file bound. To compare a config-driven source
with that inspection, set its `max_file_bytes` filesystem option or
`max_response_bytes` HTTP option to the intended bound. HTTP native publication
also requires `file_manifest: true`. A lower provider limit can reject a skill
that fits the extension's total limit.

### Native Python API

```python
import asyncio
from pathlib import Path

from agentskills_core import Skill
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_mcp_server import create_native_mcp_server

provider = LocalFileSystemSkillProvider(Path("./skills"))
server = asyncio.run(create_native_mcp_server(
        [Skill("incident-response", provider)], name="Native Skills"
))
server.run()
```

The builder also accepts an existing `SkillRegistry`. Raw `Skill` handles avoid
legacy metadata parsing, including its BOM and ASCII-name restrictions. Native
validation accepts current-spec Unicode lowercase names and preserves every
JSON-compatible author field. Known optional fields retain their specified types.
For example, `metadata` values must be strings. SDK-specific list-valued tags in
that mapping require an authored format change before native publication.

Duplicate YAML keys, non-JSON values such as unquoted dates, non-finite numbers,
and recursive values fail publication. Valid YAML merges retain their resolved
values. Expanded frontmatter JSON is bounded at 16 MiB.

### Publication Boundaries

Each skill is limited to 512 files and 16 MiB. By default, the builder retains at
most 128 skills and 64 MiB of captured file bytes. `max_skills` and
`max_total_bytes` control those aggregate limits. Provider per-file limits apply
as well. Publication fails without returning a server when a capture, manifest,
limit, or URI conflict is invalid. Use trusted, immutable sources during capture
and restart the server to publish changes.

`skill_paths` maps handle IDs to unescaped paths ending in the declared skill
name, such as `{"refunds": "billing/refunds"}`. Without an override, a differing
handle ID becomes a prefix, so an alias cannot replace the final name segment.
Names may repeat at distinct canonical URIs. Register nested skills explicitly
and map their paths under the parent, such as `{"child": "parent/child"}`.
Their files remain in the parent manifest too. Overlapping captures must agree
on both directory membership and every shared file's bytes.

`page_size` defaults to 100 complete entries. `listed_skill_ids` can select a
partial or empty listing, but never restricts direct lookup or resource access.
It is not an authorization control. All supplied skills must be appropriate for
the server's audience.

Canonical reads use standard base64 blob resources, including for `SKILL.md`.
Decode the blob before checking byte size, SHA-256 digest, and frontmatter.
There are no SDK envelopes, truncation, image conversion, or script execution.
Cache hints are `ttlMs: 0` and `cacheScope: "private"`. Captured bytes remain
unchanged for the server instance, but cache hints are not an integrity guarantee.

Hosts remain responsible for origin-scoped identity and reads, lazy retrieval,
digest and frontmatter verification, and explicit per-skill consent. Reading is
not activation. Parent approval does not approve nested skills, and
`allowed-tools` grants no host permissions automatically. Digests establish
consistency, not publisher trust. Remote HTTP deployments also need authenticated
transport, TLS, and audience isolation beyond this builder.

The tested matrix above distinguishes native Skills support from ordinary
resources access. Native checks now cover in-process, real stdio, and loopback
Streamable HTTP. Host-specific Skills certification remains a separate release
gate, including consent, origin isolation, and verification before activation.

## Quick Start (CLI)

Create a `server.json` config file:

```json
{
    "name": "My Skills Server",
    "skills": [
        {
            "id": "incident-response",
            "provider": "fs",
            "options": {"root": "./skills"}
        }
    ]
}
```

Start the server:

```bash
python -m agentskills_mcp_server --config server.json
```

With Streamable HTTP transport:

```bash
python -m agentskills_mcp_server --config server.json --transport streamable-http
```

The server listens on `http://127.0.0.1:8000/mcp`.

### Remote HTTP Deployment Boundaries

Keep the backend listener private. A remote deployment needs a TLS-terminating,
authenticated endpoint in front of it, or an equivalent secured ASGI deployment.
The local CLI commands do not configure a public OAuth resource server.

Before exposing `/mcp`, validate these deployment controls:

- Use MCP-compatible authorization discovery and validate issuer, audience, expiry, and required scopes for the public resource identifier
- Enforce the intended server audience and skill access policy, not `listed_skill_ids`, which only filters enumeration
- Restrict accepted hosts and browser origins, including forwarded-header trust at the proxy boundary
- Preserve streaming responses and supported HTTP methods without proxy buffering or unintended timeouts
- Route stateful sessions consistently when the deployment uses session state
- Keep bearer tokens out of public MCP URLs, and redact provider credentials from logs and published configuration
- Test rejected and expired credentials, cross-origin requests, disconnect cleanup, and exact native bytes through the public endpoint

The authentication component must validate credentials before traffic reaches
the private backend. Forwarding an unchecked `Authorization` header is not
authentication. Account for the backend's host and origin protections when
configuring the trusted proxy, rather than disabling them without a replacement.

Real loopback HTTP and stdio interoperability are tested. A production gateway,
TLS setup, authorization server, and host-specific approval workflow are not
certified by those tests or by `--check`. A host must still verify manifests and
obtain per-skill consent before activation. Use legacy mode when its client lacks
native Skills support.

### MCP Client Integration

Use a client that supports the selected MCP transport. Ordinary legacy
tools/resources connectivity does not establish native Skills support.

Stdio (local):

```json
{
    "command": "python",
    "args": ["-m", "agentskills_mcp_server", "--config", "server.json"]
}
```

Streamable HTTP (remote):

```json
{
    "url": "http://127.0.0.1:8000/mcp"
}
```

## Config Reference

The `server.json` file supports the following structure:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `str` | Yes | Display name shown to MCP clients |
| `instructions` | `str` | No | Server-level instructions sent during handshake |
| `skills` | `list` | Yes | One or more skill definitions (see below) |
| `mode` | `str` | No | `legacy` by default, or `native` for the official Skills extension |
| `skill_paths` | `dict` | No | Native handle-ID to canonical skill-path mapping |
| `listed_skill_ids` | `list` | No | Native listing selection only, not access control |
| `page_size` | `int` | No | Native entries per page, default 100 |
| `max_skills` | `int` | No | Native captured skill count, default 128 |
| `max_total_bytes` | `int` | No | Native aggregate captured byte limit, default 64 MiB |

Each skill entry:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | `str` | Yes | Skill identifier |
| `provider` | `str` | Yes | Provider type: `"fs"` or `"http"` |
| `options` | `dict` | No | Provider-specific options |

**Provider options:**

- `fs` accepts `root` (default `"."`) and `max_file_bytes`.
- `http` accepts `base_url`, `headers`, `params`, `resource_manifest`,
  `file_manifest`, and `max_response_bytes`.

Only `"fs"` and `"http"` are supported as provider types.

### Environment Variable Substitution

String values in the config file may contain `${VAR}` placeholders that are resolved from environment variables at load time:

```json
{
    "name": "My Skills Server",
    "skills": [
        {
            "id": "cloud-runbooks",
            "provider": "http",
            "options": {
                "base_url": "https://cdn.example.com/skills",
                "headers": { "Authorization": "Bearer ${API_TOKEN}" },
                "params": { "sig": "${SAS_TOKEN}" }
            }
        }
    ]
}
```

Unset variables resolve to an empty string and a warning is logged.

## Programmatic Usage

For custom providers or advanced setups, use the Python API directly:

```python
from agentskills_core import SkillRegistry
from agentskills_mcp_server import create_mcp_server

registry = SkillRegistry()
await registry.register("incident-response", my_custom_provider)  # any SkillProvider

server = create_mcp_server(registry, name="My Skills Server")
server.run()  # stdio by default
```

## Agent Framework Context Provider

If you're using [Microsoft Agent Framework](https://pypi.org/project/agent-framework/), `AgentSkillsMcpContextProvider` bridges an MCP session into the Agent Framework lifecycle. It reads the skills catalog and usage-instruction resources from the MCP server and injects them as session instructions on every `agent.run()` call.

> **Note:** This adapter only injects instructions, not tools. Agent Framework's MCP tool classes (`MCPStdioTool`, `MCPStreamableHttpTool`, etc.) handle tool registration natively.

```bash
pip install agentskills-mcp-server[agentframework]
```

```python
from agent_framework import Agent, MCPStdioTool
from agentskills_mcp_server import AgentSkillsMcpContextProvider

mcp_skills = MCPStdioTool(
    name="skills",
    command="python",
    args=["-m", "agentskills_mcp_server", "--config", "server.json"],
)

async with mcp_skills:
    skills_context = AgentSkillsMcpContextProvider(
        session=mcp_skills.session,
    )
    agent = Agent(
        client=client,  # any Agent Framework chat client
        name="SREAssistant",
        instructions="You are an SRE assistant.",
        tools=mcp_skills,
        context_providers=[skills_context],
    )
    response = await agent.run("What severity is a full DB outage?")
```

> See [examples/agent-framework/](https://github.com/pratikxpanda/agentskills-sdk/tree/main/examples/agent-framework) for full working demos including client setup.

| Parameter | Default | Description |
| --- | --- | --- |
| `session` | *(required)* | An MCP `ClientSession`, typically from `mcp_tool.session` |
| `skills_instruction_prompt` | Built-in template | Custom prompt template. Must contain `{skills_catalog}` and `{tools_usage_instructions}` placeholders. |
| `skills_catalog_format` | `"xml"` | Skills catalog format — `"xml"` or `"markdown"`. |
| `source_id` | `"agentskills_mcp"` | Unique identifier for this provider instance. |

## Tools

The server exposes tools that let the LLM agent access skill content:

| Tool | Parameters | Description |
| --- | --- | --- |
| `get_skill_metadata` | `skill_id` | Read frontmatter (name, description, etc.) |
| `get_skill_body` | `skill_id` | Load full skill instructions |
| `get_skill_outline` | `skill_id` | List the body's sections, keys and token costs |
| `get_skill_section` | `skill_id`, `key` | Load one section of the body |
| `list_skill_resources` | `skill_id` | List bundled references, scripts and assets |
| `get_skill_reference` | `skill_id`, `name` | Read a reference document |
| `get_skill_script` | `skill_id`, `name` | Read a script |
| `get_skill_asset` | `skill_id`, `name` | Read an asset |

`get_skill_outline` exists so a large skill is not all-or-nothing. Its rendered text carries the whole-body cost alongside the per-section costs and says outright when `get_skill_body` is the cheaper call — a section fetch is not free, it costs a tool call and a model turn on top of the outline. Section keys are flat slugs and sections do not nest, so fetching a parent does not include what is indented under it in the outline.

`list_skill_resources` returns a JSON object keyed by resource kind. Not every backend can enumerate resources — a plain static HTTP host cannot. Rather than surfacing an exception, the tool returns `{"supported": false, "note": "..."}` in that case: "this cannot be listed" is something the model can act on by falling back to the names in the skill body, not an error worth retrying.

## Resources

The server provides resources for system-prompt context:

| URI | Description |
| --- | --- |
| `skills://catalog/xml` | XML catalog of all registered skills |
| `skills://catalog/markdown` | Markdown catalog of all registered skills |
| `skills://tools-usage-instructions` | Workflow instructions for using the tools |
| `skills://{skill_id}/resources` | Resource listing for a single skill |

The MCP client reads these resources and injects them into the system prompt, giving the agent both *what* skills exist and *how* to interact with them.

## Single-Skill Fast Path

A server exposing one skill makes the client pay the whole discovery apparatus — a catalog listing one entry, eight tool definitions, usage instructions describing a selection workflow, and a model round trip while the agent calls `get_skill_body` — to reach content there was never a choice about.

```python
from agentskills_core import resolve_fast_path

fast_path = await resolve_fast_path(registry)
server = create_mcp_server(registry, name="my-skills", fast_path=fast_path)
```

`resolve_fast_path` returns `None` unless the effective skill set is exactly one and its body fits under a token ceiling, and `fast_path=None` is the normal path — so the call above is safe unconditionally. When it fires:

- Both `skills://catalog/*` resources serve the skill's body directly, so an existing client that already injects the catalog needs no change.
- `skills://tools-usage-instructions` drops the selection workflow, which would otherwise point the model at a catalog that is no longer there and at tools that are no longer registered.
- The four body-access tools are **never registered**. MCP has no way to hide a registered tool later, so they are omitted at construction rather than declined at call time.
- The four resource tools remain.

The ceiling, the arithmetic behind its default, and why resource tools stay are documented in the [core README](https://github.com/pratikxpanda/agentskills-sdk/tree/main/packages/core/agentskills-core#single-skill-fast-path). Because tools are fixed at construction, rebuild the server if the registry changes.

## API

### `AgentSkillsMcpContextProvider(session, *, skills_instruction_prompt=None, skills_catalog_format="xml", source_id=None)`

A `ContextProvider` that reads the skills catalog and tools-usage-instructions from an MCP session and injects them as session instructions via `before_run()`. Requires the `[agentframework]` extra.

### `create_mcp_server(registry, *, name, instructions=None, max_inline_binary_bytes=65536, fast_path=None, vision=False, max_inline_image_bytes=5242880)`

| Parameter | Type | Description |
| --- | --- | --- |
| `registry` | `SkillRegistry` | The registry whose skills are exposed |
| `name` | `str` | Display name for the MCP server (required) |
| `instructions` | `str \| None` | Optional server-level instructions sent to clients |
| `max_inline_binary_bytes` | `int` | Size ceiling for inlining binary resources as base64 |
| `fast_path` | `FastPath \| None` | From `resolve_fast_path`; inlines a lone skill's body and drops the body-access tools |
| `vision` | `bool` | Return bundled images as native `ImageContent` instead of a base64 envelope |
| `max_inline_image_bytes` | `int` | Size ceiling for native images; only consulted when `vision` is on |

Returns the installed SDK's configured server instance, ready for `server.run()`.

Supported transport modes: `stdio` (default), `streamable-http`.

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

Base64 costs roughly 1.37 characters per byte, so binaries above 64 KiB are described rather than inlined - `"encoding": "none"` plus a `note` explaining the omission. Adjust the ceiling with `create_mcp_server(..., max_inline_binary_bytes=256 * 1024)`.

## Images

A base64 envelope is the right answer for an opaque binary and the wrong one for
a diagram: the model gets a wall of characters where a picture was. Pass
`vision=True` and bundled images come back as native `ImageContent` instead:

```python
server = create_mcp_server(registry, name="skills", vision=True)
```

It is off by default because handing an image to a text-only model is an API
error from the provider, not a degraded answer, and there is no reliable way to
ask a model whether it can see. The client knows which model is on the other end;
the server does not.

PNG, JPEG, GIF and WebP qualify, and only when the leading bytes say so - a name
is a claim, bytes are evidence. PDF is excluded because support varies by model,
and SVG because it is already text the model can read. Everything else keeps the
JSON envelope exactly as above, including images past `max_inline_image_bytes`
(5 MiB by default, against 64 KiB for opaque binaries - base64 in a text field is
billed per byte, while a native image is billed by tile count).

See [ADR 0009](https://github.com/pratikxpanda/agentskills-sdk/blob/main/docs/adr/0009-native-image-content.md).

## License

MIT
