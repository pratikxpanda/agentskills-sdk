---
title: Skill Selection
description: Rank registered skills for a host-provided query with lexical or embedding selectors.
---

Narrows the catalog to the skills a query is actually about.

```bash
pip install agentskills-retrieval
```

The selector needs an already populated `SkillRegistry` and a query supplied by your host.
`LexicalSelector` needs no model SDK. `EmbeddingSelector` requires your own async embedder and
client lifecycle. Neither injects or activates skills.

See the [complete quick start and embedder example](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/retrieval/agentskills-retrieval/README.md#usage).

::: agentskills_retrieval
    options:
      show_root_heading: true
