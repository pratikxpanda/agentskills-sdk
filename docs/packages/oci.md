---
title: OCI Provider
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

```bash
pip install agentskills-oci
```

The repository must already contain artifacts in the required format. The
[package guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/providers/agentskills-oci/README.md#read-skills)
has a runnable async reader and the full artifact-field contract. The package is read-only
and does not turn arbitrary container images into skills.

ORAS uses its token auth backend and local Docker-compatible credentials by
default. Pass a configured ORAS client for other registry authentication or
TLS settings. Layer digests establish byte consistency. Use the core trust
policy after capturing a complete skill snapshot when publisher verification
is required.

## API Reference

::: agentskills_oci.OCISkillProvider
    options:
      show_root_heading: true
