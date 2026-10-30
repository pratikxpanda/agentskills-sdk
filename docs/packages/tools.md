---
title: CLI Tooling
description: Scaffold, validate, inspect, pin, and serve Agent Skills.
---

Scaffold, validate, lint, inspect, evaluate, lock, and serve skills.

```bash
pip install agentskills-tools
```

Run the CLI against a skill folder or a directory containing skill folders:

```bash
agentskills validate ./skills
agentskills lint ./skills
agentskills inspect ./skills --native
```

## Serve Skills

```bash
pip install "agentskills-tools[serve]"
agentskills serve ./skills --check
agentskills serve ./skills --transport stdio
```

The `serve` extra installs the MCP extension. `--check` validates local publication without
opening a listener. It does not test authentication or host behavior. Add `--skill-prompts`
to opt in to a user-invoked prompt, which grants no permissions.

The complete command options, evaluation-client contract, JSON output, and exit codes are in the
[package guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/tools/agentskills-tools/README.md).

## API Reference

::: agentskills_tools
    options:
      show_root_heading: true

The `lock` command records a Git source, resolved commit, and canonical per-file digests. Use
`agentskills lock verify` against a local clone to check the pinned commit and content offline.
Use `agentskills lock update` to resolve a new revision from the same source. Roll back by
restoring an earlier lockfile from version control and verifying it against that revision. These
commands require `agentskills-tools` v0.8.0 or newer.
