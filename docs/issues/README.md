---
title: Issue Specifications
description: Milestone specifications and their relationship to the SDK roadmap and GitHub issues.
---

> Detailed write-ups for [roadmap](../ROADMAP.md) items, kept in the repo whether or not they
> have been filed as GitHub issues yet.

The roadmap says *what* and *why* in one line per item. These files carry the full
specification: problem statement, proposed approach, open questions, and acceptance criteria.

Each file covers one milestone, in the same order as the corresponding roadmap table.

| Milestone | Items | State |
| --- | --- | --- |
| [v0.3: Foundations](./v0.3.md) | 12 | Shipped |
| [v0.4: Developer Experience](./v0.4.md) | 12 | Shipped |
| [v0.5: Agent Effectiveness](./v0.5.md) | 6 | Shipped |
| [v0.6: MCP-First Skills](./v0.6.md) | 7 | Included in v0.6.0. Deployment validation remains explicitly deferred. |
| v0.7: Trust & Operability | 7 | Included in v0.7.0. See the [control contracts and validation boundaries](../trust-and-operability.md) and [roadmap](../ROADMAP.md#v07-trust-operability). |
| [v0.8: Portable Distribution](./v0.8.md) | 5 | Git, lockfile, MCP client/composition, prompt, Azure Blob, and OCI acceptance criteria. Additional sources remain demand-gated. |
| [v0.9: Compatibility and Production Readiness](./v0.9.md) | 7 | Published as v0.9.0; external deployment and post-publication validation gates remain open. |
| [v1.0: Stability](./v1.0.md) | 4 | Proposed scope; stable API, compatibility, release, and interoperability decisions remain open. |

A milestone gets a specification once its items are concrete enough to have acceptance criteria.
The v1.0 specification is a proposal; its stable API and compatibility decisions remain open.
The v0.3 to v0.6 files are historical records. They describe packages and APIs, such as the
LangChain and Agent Framework integrations, that v0.7 removed.

## Relationship to GitHub Issues

| | Lives here | Lives on the issue |
| --- | --- | --- |
| Problem statement, proposed design, acceptance criteria | yes | a link back to here |
| Status, assignee, milestone, discussion, linked PRs | | yes |

When an item is filed, add its number to the heading so the two stay connected:

```markdown
## 3. Stop blocking the event loop in the filesystem provider ([#42](https://github.com/pratikxpanda/agentskills-sdk/issues/42))
```

The issue body should link back to its section here rather than duplicating it: duplicated
text is what drifts. If the design changes during implementation, **update the spec here**: the
issue thread records the discussion, this file records the conclusion.

Shipped items stay, marked `**Status:** Shipped in vX.Y`, so the reasoning behind a change
remains findable. An item whose design turned out to be wrong gets a note explaining why rather
than being quietly deleted.

## Labels

| Prefix | Values |
| --- | --- |
| `theme:` | `correctness`, `performance`, `resilience`, `agent-effectiveness`, `interoperability`, `trust`, `operability`, `dx`, `ecosystem`, `project-health` |
| `package:` | `core`, `fs`, `git`, `http`, `mcp-server`, `tools`, `testing`, `retrieval`, `adapters` |
| `type:` | `bug`, `feature`, `docs`, `chore` |
| flat | `good-first-issue`, `help-wanted`, `breaking-change` |
