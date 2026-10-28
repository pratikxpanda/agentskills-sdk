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

The repository is available as `provider.repository`, and the resolved commit is available as
`provider.resolved_commit` after the first provider operation. Use `capture_skill` to produce the
shared core snapshot with per-file SHA-256 digests:

```python
from agentskills_core import capture_skill

snapshot = await capture_skill(registry.get_skill("incident-response"))
[(file.path, file.digest) for file in snapshot.files]
```

Each checkout defaults to a 256 MiB limit. The cache defaults to 1 GiB total and evicts the
least-recently-used inactive checkout when it needs space. Active providers in the current process
and other processes sharing the cache are protected by lease locks. Release acceptance criteria
remain open work for this milestone.

::: agentskills_git.GitSkillProvider
    options:
      show_root_heading: true

::: agentskills_git.GitSkillProviderError
    options:
      show_root_heading: true
