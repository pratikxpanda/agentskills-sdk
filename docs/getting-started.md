---
title: Getting Started
description: Publish native MCP Skills or use the framework-neutral Python APIs.
---

## Install what you need

The SDK is split into focused packages.

- `agentskills-core` for registry and validation
- One provider (`agentskills-fs` or `agentskills-http`)
- `agentskills-mcp-server` for native Skills delivery to a conforming host

v0.7 is in development. Install the checkout until it is published:

```bash
pip install ./packages/core/agentskills-core ./packages/providers/agentskills-fs ./packages/integrations/agentskills-mcp-server
```

## Publish Skills

```bash
python -m agentskills_mcp_server --config examples/server-fs.json --check
python -m agentskills_mcp_server --config examples/server-fs.json
```

The server requires MCP SDK 2.2+ and protocol 2026-07-28. A host must support the
Skills extension, verify manifests and content, and obtain approval before
activation. Ordinary MCP tools connectivity is insufficient. See the
[migration guide](mcp-migration.md) before upgrading a framework integration.
For signed publication, content policy, and refresh, see
[Trust and Operability](trust-and-operability.md).

## Use Local Core APIs

```python
from pathlib import Path

from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider

registry = SkillRegistry()
await registry.register_all(LocalFileSystemSkillProvider(Path("./skills")))
```

## Build a Local Catalog

```python
catalog = await registry.get_skills_catalog(format="xml")
```

Custom hosts can use this catalog and fetch bodies or sections through core APIs.
The SDK does not inject it automatically. Native MCP discovery instead uses
`skills/list` and `skills/get`, with on-demand original files at `skill://` URIs.

## Author and validate skills

```bash
pip install agentskills-tools
agentskills init incident-response --path ./skills
agentskills validate ./skills
agentskills lint ./skills
```

For publication options, see the [MCP server](packages/mcp-server.md).
