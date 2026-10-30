---
title: agentskills-oci
description: Read Agent Skills from OCI Distribution registries
---

Read-only OCI distribution support for progressive, digest-verified Agent
Skills files. Each skill occupies one registry tag. Its OCI image manifest uses
`application/vnd.agentskills.skill.v1` as `artifactType`, and each canonical
file is a raw layer labeled with `org.opencontainers.image.title`.

## Install

```bash
pip install agentskills-oci
```

Requires Python 3.12 or newer. The dependency is the ORAS Python SDK. You do not need the
separate ORAS CLI to read skills with this provider.

## Read Skills

The repository must already contain skill artifacts in the format described below. Replace
the repository and skill ID with yours:

```python
import asyncio

from agentskills_oci import OCISkillProvider


async def main() -> None:
    async with OCISkillProvider("ghcr.io/acme/skills") as provider:
        print(await provider.discover())
        print(await provider.list_files("incident-response"))
        print(await provider.read_file("incident-response", "SKILL.md"))


asyncio.run(main())
```

Discovery and listing fetch tags and manifests, not file layers. `read_file` downloads only
the requested layer and verifies its size and SHA-256 digest. The provider caches manifests
per instance, so use immutable tags or recreate the provider when updating a source.

## Artifact Format

This provider is read-only. Publishing is handled by your registry tooling, which must produce
the following format. An arbitrary container image or a default ORAS file push is not sufficient.

| Field | Required value |
| --- | --- |
| Tag | Skill ID, such as `incident-response` |
| `schemaVersion` | `2` |
| Manifest `mediaType` | `application/vnd.oci.image.manifest.v1+json` |
| Manifest `artifactType` | `application/vnd.agentskills.skill.v1` |
| Manifest title annotation | `org.opencontainers.image.title` must equal the tag |
| Layer `mediaType` | `application/vnd.agentskills.file.v1` for every file |
| Layer title annotation | Relative POSIX path, such as `SKILL.md` or `references/guide.md` |
| Layer descriptor | Exact byte size and `sha256:` digest of the uploaded file |

Include `SKILL.md` as a layer and preserve its original YAML frontmatter and body. Duplicate
paths, traversal, missing skill files, unsupported digests, and oversized descriptors are rejected.
Defaults are 512 files, 10 MiB per file, and 16 MiB declared total size per skill. Configure
`max_files`, `max_file_bytes`, and `max_total_bytes` in the constructor.

## Authentication and Cleanup

ORAS uses its token auth backend and local Docker-compatible credentials by
default. Pass a configured ORAS client for other registry auth, TLS, or signing
controls. Layer descriptors are checked against the fetched bytes. Registry
digests establish consistency, not publisher identity. Use the core trust
policy after capturing a complete skill snapshot when publisher verification
is required.

The async context manager closes the HTTP session only when the provider created the ORAS
client. Injected clients remain caller-owned. TLS verification is enabled by default. Keep
`insecure=False` and `tls_verify=True` for production registries.
