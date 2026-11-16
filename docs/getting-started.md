---
title: Getting Started
description: Publish native MCP Skills or use the framework-neutral Python APIs.
---

## Install what you need

The SDK is split into focused packages.

- `agentskills-core` for registry and validation
- One provider, such as filesystem, HTTP, Git, Azure Blob, Azure Files, or OCI
- `agentskills-mcp-extension` for native Skills delivery to a conforming host

Install the native MCP server with the filesystem provider:

```bash
pip install "agentskills-tools[serve]"
```

## Publish Skills

```bash
agentskills serve --config examples/server-fs.json --check
agentskills serve --config examples/server-fs.json
```

Config-driven serving requires v0.9 or newer. MCP-only environments can install
`agentskills-mcp-extension[fs]` and use `python -m agentskills_mcp_extension --config ...` instead.
The v0.9 config resolver supports all six provider types. Install each selected source package
separately. Azure Blob and Azure Files retain independent SDK extras.

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

For publication options, see the [MCP server](packages/mcp-extension.md).
