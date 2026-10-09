---
title: MCP Migration
description: Breaking changes and migration boundaries for the native-only v0.7 release.
---

## Additional v0.7 Controls

HTTP providers now block private-network destinations by default and never follow
redirects. Internal hosts and caller-supplied HTTPX clients require explicit
`allow_private_network=True`. Caller-supplied clients own their network enforcement.
`base_url` no longer accepts embedded credentials, query strings, or fragments.
Pass upstream credentials through `headers` or `params`, never from inbound MCP tokens.

The native factory also supports publisher verification, content policy,
controlled refresh, verified outage fallback, telemetry, and authenticated remote
HTTP integration. See [Trust and Operability](trust-and-operability.md) for the
configuration contract and host/deployment boundaries.

## v0.7 Breaking Changes

v0.6.0 shipped the native integration deprecations. v0.7 is native-Skills-only
and removes those integrations and legacy MCP delivery.
The maintainer selected this direction on 2026-10-06, accepting the loss of the
previous framework-client paths.

| Removed surface | v0.7 direction |
| --- | --- |
| `agentskills-langchain` | No new distribution. Use a host implementing native MCP Skills |
| `agentskills-agentframework` | No new distribution. Context lifecycle behavior is host-owned |
| `AgentSkillsMcpContextProvider` and `[agentframework]` | Removed from the maintained MCP package |
| MCP SDK 1.x | Server requires `mcp>=2.2,<3` |
| Eight legacy tools and `skills://` catalog resources | Use `skills/list`, `skills/get`, and `resources/read` on `skill://` URIs |
| Synchronous `create_mcp_server` | Await the native factory. The old `.server` module is removed |
| Legacy server fast path and image/tool options | No eager injection or tool conversion in native delivery |
| `agentskills serve --native` | Remove the flag. Serving is always native |
| `mode` configuration key | Removed. Unknown keys, including `mode`, are rejected |
| `create_native_mcp_server` and `build_native_server` | Use `create_mcp_server` and `build_server` |
| Base64 `blob` for every file | UTF-8 text without NUL is read as `text`, other files as `blob` |

`agentskills-adapters` imports instruction formats and remains supported. Core,
filesystem, HTTP, retrieval, testing, CLI tooling, and MCP remain maintained:
eight distributions in lockstep releases.

## Source Retention

Retired source and dependent examples are deleted from the active tree, with no
`archived/` directory. An in-tree archive would still look vendorable and would create
ambiguity about scanning, testing, dependency updates, and support. The immutable
[v0.6.0 source tag](https://github.com/pratikxpanda/agentskills-sdk/tree/v0.6.0)
and [versioned documentation](https://pratikxpanda.github.io/agentskills-sdk/0.6.0/)
preserve the historical implementation. Existing PyPI releases are not deleted or
yanked because of retirement. Retired packages do not track future framework
releases and receive no new lockstep releases.

## Framework Compatibility

The v0.6 LangChain and Microsoft Agent Framework smoke examples verified ordinary
MCP tools and resources, not native Skills activation. Those examples depended on
the removed legacy API and have been removed from the active tree. Their historical
success is not evidence of v0.7 compatibility.

Applications without a native Skills host must stay on the v0.6 release family in
an isolated environment while migrating. Pin the entire relevant package set,
including core and providers, rather than mixing retired integrations with 0.7
dependencies. For example, a historical filesystem LangChain environment pins
`agentskills-langchain==0.6.0`, `agentskills-core==0.6.0`, and
`agentskills-fs==0.6.0`. Preserve its tested framework dependency lock too.
This is a compatibility hold, not a promise of continued maintenance or security
support for retired integrations.

| Former behavior | Native-only alternative or explicit gap |
| --- | --- |
| Framework tool wrappers | No direct replacement. A conforming Skills host is required |
| Automatic catalog injection | Host selects metadata and injects approved content |
| Query-time retrieval | `agentskills-retrieval` remains available for host integration |
| Prompt caching and loaded-skill pruning | Host implements and tests conversation-aware state |
| Single-skill fast path | Core helper remains for custom hosts, never automatic at discovery |
| Section-level tools | Core section APIs remain local. Native transport serves original files |
| Vision-native tools | Original blob resources, with decoding and rendering owned by the host |
| Loaded-skill metadata | Host-owned session state, no bridge replacement |
| Approval and execution | Host verifies content and obtains consent, then applies its own policy |

## Update Server Code

```python
from agentskills_core import Skill
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_mcp_server import create_mcp_server

provider = LocalFileSystemSkillProvider("./skills")
server = await create_mcp_server([Skill("incident-response", provider)])
```

`create_mcp_server` captures immutable snapshots. Programmatic servers publish
changed content with `await server.refresh()`. HTTP providers must
enable complete file manifests with `file_manifest=True`.

```bash
agentskills inspect ./skills --native
agentskills serve ./skills --check
agentskills serve ./skills
```

Use MCP SDK 2 `Client` for protocol `2026-07-28` and extension negotiation.
Canonical resources preserve full frontmatter, original bytes, nested paths, and
binary files. Discovery must not be treated as activation.

## Trust and Deployment

Skills are untrusted instructions. Hosts must retain server-plus-URI identity,
verify manifests and bytes, obtain content-bound approval, and treat nested skills
as separate consent decisions. Hash consistency does not prove authorship or safety.
Scripts are not executed by resource reads and `allowed-tools` grants no permissions.

TLS, authorization, origin/host validation, and audience isolation are deployment
responsibilities. Do not pass inbound bearer tokens to upstream providers.
Local preflight and transport tests do not certify production security or model
behavior. See [Trust and Operability](trust-and-operability.md) for publisher
verification, content policy, refresh, and network controls.
