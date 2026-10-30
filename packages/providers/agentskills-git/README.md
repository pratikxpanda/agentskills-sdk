---
title: agentskills-git
description: Read Agent Skills from Git repositories at immutable commits.
---

[![PyPI](https://img.shields.io/pypi/v/agentskills-git)](https://pypi.org/project/agentskills-git/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

Read Agent Skills from a Git repository at a ref resolved to an immutable commit. The provider
uses Git and delegates skill reads to `agentskills-fs`.

## Availability

Added in v0.8.0, this provider resolves a branch, tag, or commit on first access and keeps using
that commit from its local cache.
It exposes the repository and resolved commit for source identity, and supports a repository
subdirectory containing skill directories.

## Requirements

Python 3.12 or newer and the Git command-line executable must be available on `PATH`.

## Usage

```python
from pathlib import Path

from agentskills_core import SkillRegistry
from agentskills_git import GitSkillProvider

provider = GitSkillProvider(
    "https://github.com/example/skills.git",
    "main",
    Path(".cache/agent-skills"),
    subdirectory="skills",
)
registry = SkillRegistry()
await registry.register_all(provider)

print(provider.resolved_commit)
```

## Security and limits

The provider does not run repository hooks, submodules, or skill scripts. It ignores system and global
Git configuration and disables the `ext` transport. Symlink entries are rejected. The cache has a
configurable size limit per checkout (`max_cache_bytes`, 256 MiB by default) and a 1 GiB total
limit (`max_total_cache_bytes`). Least-recently-used inactive checkouts are evicted to stay within
the total limit. File locks protect active checkouts across processes. Remote authentication uses Git's supported transport
mechanisms, except credentials from global Git configuration are not loaded by this provider.

Use the shared core snapshot API to capture original files and their SHA-256 digests:

```python
from agentskills_core import capture_skill

snapshot = await capture_skill(registry.get_skill("incident-response"))
for file in snapshot.files:
    print(file.path, file.digest)
```

Broader Git host compatibility is still being tested.
