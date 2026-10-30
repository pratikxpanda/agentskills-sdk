---
title: Git Provider
description: Read Agent Skills from a Git repository at a resolved commit.
---

The Git provider resolves a configured ref to a commit on first access and
serves skills from that checkout. Git must be installed and available on `PATH`.

The selected repository directory must contain skill directories directly beneath it. Use
`subdirectory` when skills live below the repository root.

```bash
pip install agentskills-git
```

The repository is available as `provider.repository`, and the resolved commit is available as
`provider.resolved_commit` after the first provider operation. The
[package guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/providers/agentskills-git/README.md#usage)
has a complete async registration and snapshot example. Create a new instance with
`refresh=True` to refetch a mutable ref. There is no public close method; the cache lease is
released by the provider's finalizer.

Each checkout defaults to a 256 MiB limit. The cache defaults to 1 GiB total and evicts the
least-recently-used inactive checkout when it needs space. Active providers in the current process
and other processes sharing the cache are protected by lease locks. See the
[v0.8 acceptance criteria](../issues/v0.8.md#git-provider).

::: agentskills_git.GitSkillProvider
    options:
      show_root_heading: true

::: agentskills_git.GitSkillProviderError
    options:
      show_root_heading: true
