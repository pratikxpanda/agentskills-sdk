---
title: Git Provider
description: Read Agent Skills from a Git repository at a resolved commit.
---

The Git provider is under development for v0.8 and is not yet published. It resolves a configured
ref to a commit on first access and serves skills from that checkout. Git must be installed and
available on `PATH`.

The selected repository directory must contain skill directories directly beneath it. Use
`subdirectory` when skills live below the repository root.

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
```

The resolved commit is available as `provider.resolved_commit` after the first provider operation.
The current cache limit applies per checkout. Total cache bounds, eviction, and content digest
reporting remain open work for this milestone.

::: agentskills_git.GitSkillProvider
    options:
      show_root_heading: true

::: agentskills_git.GitSkillProviderError
    options:
      show_root_heading: true
