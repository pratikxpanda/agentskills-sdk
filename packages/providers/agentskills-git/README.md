---
title: agentskills-git
description: Read Agent Skills from Git repositories at immutable commits.
---

[![PyPI](https://img.shields.io/pypi/v/agentskills-git)](https://pypi.org/project/agentskills-git/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

Read Agent Skills from a Git repository at a ref resolved to an immutable commit. The provider
uses Git and delegates skill reads to `agentskills-fs`.

## Install

```bash
pip install agentskills-git
```

Python 3.12 or newer and the Git command-line executable must be available on `PATH`.
The configured repository must already contain valid skill directories. Set `subdirectory`
when they are beneath a folder such as `skills/` rather than the repository root.

## Usage

```python
import asyncio
from pathlib import Path

from agentskills_core import SkillRegistry, capture_skill
from agentskills_git import GitSkillProvider


async def main() -> None:
    provider = GitSkillProvider(
        "https://github.com/example/skills.git",
        "main",
        Path(".cache/agent-skills"),
        subdirectory="skills",
    )
    registry = SkillRegistry()
    await registry.register_all(provider)
    print(provider.resolved_commit)

    snapshot = await capture_skill(registry.get_skill("incident-response"))
    for file in snapshot.files:
        print(file.path, file.digest)


asyncio.run(main())
```

Replace the repository URL, ref, and skill ID with your source. The directory layout matches
the [filesystem provider](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/providers/agentskills-fs/README.md#expected-directory-layout).
A branch or tag is resolved on first access. That provider instance continues to use the same
commit even when the remote ref moves. Construct a new provider with `refresh=True` to fetch
the ref again. The provider holds a cache lease for its lifetime and releases it through its
finalizer. There is no public `close` or `aclose` method.

## Security and limits

The provider does not run repository hooks, submodules, or skill scripts. It ignores system and global
Git configuration and disables the `ext` transport. Symlink entries are rejected. The cache has a
configurable size limit per checkout (`max_cache_bytes`, 256 MiB by default) and a 1 GiB total
limit (`max_total_cache_bytes`). Least-recently-used inactive checkouts are evicted to stay within
the total limit. File locks protect active checkouts across processes. Remote authentication uses Git's supported transport
mechanisms, except credentials from global Git configuration are not loaded by this provider.

Broader Git host compatibility is still being tested.
