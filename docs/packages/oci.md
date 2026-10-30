---
title: OCI provider
description: Read digest-verified Agent Skills files from OCI Distribution registries.
---

## Artifact Layout

Each skill is an OCI artifact addressed by a tag matching the skill ID. The
manifest must use `application/vnd.agentskills.skill.v1` as `artifactType` and
the same skill ID in `org.opencontainers.image.title`. Each canonical file is
a raw layer using `application/vnd.agentskills.file.v1`; its title annotation
contains the relative POSIX file path. The provider reads manifests during
discovery and fetches file blobs only when requested.

## Usage

```python
from agentskills_oci import OCISkillProvider

async with OCISkillProvider("ghcr.io/acme/agent-skills") as provider:
    skill_ids = await provider.discover()
```

ORAS uses its token auth backend and local Docker-compatible credentials by
default. Pass a configured ORAS client for other registry authentication or
TLS settings. Layer digests establish byte consistency. Use the core trust
policy after capturing a complete skill snapshot when publisher verification
is required.

## API Reference

::: agentskills_oci.OCISkillProvider
    options:
      show_root_heading: true
