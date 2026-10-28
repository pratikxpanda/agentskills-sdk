---
title: agentskills-oci
description: Read Agent Skills from OCI Distribution registries
---

Read-only OCI distribution support for progressive, digest-verified Agent
Skills files. Each skill occupies one registry tag. Its OCI image manifest uses
`application/vnd.agentskills.skill.v1` as `artifactType`, and each canonical
file is a raw layer labeled with `org.opencontainers.image.title`.

```python
from agentskills_oci import OCISkillProvider

async with OCISkillProvider("ghcr.io/acme/skills") as provider:
    skill_ids = await provider.discover()
```

ORAS uses its token auth backend and local Docker-compatible credentials by
default. Pass a configured ORAS client for other registry auth, TLS, or signing
controls. Layer descriptors are checked against the fetched bytes. Registry
digests establish consistency, not publisher identity. Use the core trust
policy after capturing a complete skill snapshot when publisher verification
is required.
