# agentskills-git

[![PyPI](https://img.shields.io/pypi/v/agentskills-git)](https://pypi.org/project/agentskills-git/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

Read Agent Skills from a Git repository at a ref resolved to an immutable commit. The provider
uses Git and delegates skill reads to `agentskills-fs`.

## Status

This package is under development for v0.8. It is not published on PyPI. The current implementation
resolves a branch, tag, or commit on first access and keeps using that commit from its local cache.
It supports a repository subdirectory containing skill directories.

## Requirements

Python 3.12 or newer and the Git command-line executable must be available on `PATH`.

## Planned usage

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
configurable size limit per checkout. Remote authentication uses Git's supported transport
mechanisms, except credentials from global Git configuration are not loaded by this provider.

The implementation is still being developed. Cache eviction, total cache bounds, content digest
reporting, and broader Git host compatibility are not complete yet.
