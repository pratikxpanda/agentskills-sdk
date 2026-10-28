# CLI Tooling (`agentskills-tools`)

Scaffold, validate, lint, inspect, evaluate, lock, and serve skills.

```bash
pip install agentskills-tools
```

::: agentskills_tools
    options:
      show_root_heading: true

The `lock` command records a Git source, resolved commit, and canonical per-file digests. Use
`agentskills lock verify` against a local clone to check the pinned commit and content offline.
Use `agentskills lock update` to resolve a new revision from the same source. Roll back by
restoring an earlier lockfile from version control and verifying it against that revision. These
commands are under development for v0.8.0 and are not in the published v0.7.0 package.
