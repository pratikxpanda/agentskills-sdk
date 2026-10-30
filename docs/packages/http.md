---
title: HTTP Provider
description: Static HTTP skill access with explicit manifests and public-network defaults.
---

Loads skills from a static HTTP host or CDN. Connections are public-network-only by
default. See [Trust and Operability](../trust-and-operability.md).

```bash
pip install agentskills-http
```

Reading a known skill needs its `SKILL.md`. Discovery additionally needs a root `index.json`
and `skill_manifest=True`. Complete file access needs a per-skill `files` index and
`file_manifest=True`; this is required for native MCP publication.

The [package guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/providers/agentskills-http/README.md#usage)
has a runnable async example, manifest formats, authentication, client ownership, and retry
rules. Use the async context manager or close owned clients explicitly.

::: agentskills_http
    options:
      show_root_heading: true
