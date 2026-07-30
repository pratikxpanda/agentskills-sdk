# Agent Skills SDK — Roadmap

> Public roadmap for the [Agent Skills SDK](../README.md). Themes and ordering, not dates.

This document describes **what we intend to build and why**. It is intentionally coarse-grained:
detailed scoping, discussion, and progress tracking live in
[GitHub Issues](https://github.com/pratikxpanda/agentskills-sdk/issues), grouped by milestone.

Written-up specifications for the items below — problem, approach, open questions, acceptance
criteria — live in [docs/issues/](./issues/), one file per milestone.

## Product Principles

These constrain every item below. If a proposal conflicts with one of these, it needs an
explicit design doc arguing the trade-off.

1. **Spec-first.** The SDK implements the [Agent Skills open format](https://agentskills.io/specification).
   We do not invent proprietary extensions to the skill format; where we need more (e.g. `version`),
   we use optional, backward-compatible frontmatter fields and push for upstream adoption.
2. **Progressive disclosure is the contract.** Every abstraction must let an agent pay only for
   the tokens it actually needs. Anything that forces eager loading of full skill bodies is a bug.
3. **Skills are untrusted code.** Skill content lands verbatim in an agent's context. Trust,
   provenance, and integrity are first-class product features, not documentation footnotes.
4. **Small, composable packages.** `agentskills-core` stays dependency-light. Providers and
   framework integrations are optional installs and never leak into core.
5. **Framework-agnostic core, thin adapters.** Framework-specific behaviour belongs in the
   integration package. If two integrations need the same logic, it moves to core.

## Themes

| Theme | Why it matters |
|---|---|
| **Correctness & spec coverage** | Close the gaps between the SDK and the full skill format so real-world skills work unmodified. |
| **Performance & resilience** | Skills are fetched on the hot path of an agent turn. Redundant I/O is latency and cost. |
| **Agent effectiveness** | Retrieval is table stakes. The product question is whether an agent holding a skill actually performs better — and whether anyone can prove it. |
| **Interoperability** | Teams already have instructions written in other formats. Meeting them where they are beats asking them to start over. |
| **Trust & supply chain** | The differentiator for enterprise adoption. Skills are code; treat them like it. |
| **Operability** | Platform teams cannot run what they cannot see. Logs, traces, metrics, usage signals. |
| **Developer experience** | Adoption is gated on how fast someone can author, validate, and ship a skill. |
| **Ecosystem breadth** | More providers and framework integrations widen the addressable surface. |
| **Project health** | An open-source project is a product; release engineering and governance are features. |

---

## Now — v0.3 "Foundations"

Close the highest-severity correctness and performance gaps before the API surface widens.

| Item | Theme | Package(s) | Notes |
|---|---|---|---|
| Provider content caching | Performance | `agentskills-fs`, `agentskills-http` | **Implemented, awaiting release.** A single skill's `SKILL.md` was fetched up to 5x per session — twice during registration (`validate_skill()` calls `get_body()` and `get_metadata()` independently), once per catalog build, and again on each tool call. Now cached per provider instance with an explicit `invalidate()`. HTTP revalidation via `ETag` / `Last-Modified` is opt-in (`revalidate=True`) rather than default, since a conditional request per access defeats the point for the common static-host case. |
| Concurrent catalog build | Performance | `agentskills-core` | **Implemented, awaiting release.** `get_skills_catalog()` fetched metadata serially. Now fans out with `asyncio.gather` under a bounded semaphore (`SkillRegistry(catalog_concurrency=8)`); output ordering is unchanged. |
| Non-blocking filesystem I/O | Performance | `agentskills-fs` | **Implemented, awaiting release.** The provider was `async` but read synchronously, blocking the event loop. Path resolution, stat and read now run in a worker thread via `asyncio.to_thread`. |
| Resource discovery API | Correctness | `agentskills-core` + providers | **Implemented, awaiting release.** Agents had no way to learn which references/scripts/assets exist; discovery depended entirely on SKILL.md prose. `list_resources(skill_id)` is now an *optional* provider capability paired with a `supports_resource_listing` flag ([ADR 0002](adr/0002-optional-provider-capabilities.md)). The default implementation raises `ResourceListingNotSupportedError` rather than returning `{}`, so "cannot enumerate" is never mistaken for "has no resources". Filesystem enumerates directly; HTTP requires an opt-in per-skill `index.json`, which also gives the supply-chain work a natural home for integrity hashes. |
| Binary-safe resources | Correctness | `agentskills-core` + all integrations | **Implemented, awaiting release.** All three integrations decoded provider bytes with `.decode("utf-8", errors="replace")`, silently destroying images, PDFs, and archives. A shared `encode_resource_content()` now returns valid UTF-8 verbatim and wraps everything else in a base64 JSON envelope. Using MCP's native binary content blocks instead of a JSON string remains a follow-up. |
| Optional `version` frontmatter | Correctness | `agentskills-core` | **Implemented, awaiting release.** Skills had no version, so nothing could be pinned, compared, or checked for drift. `version` is now optional, validated as semver when present, returned by `get_metadata()`, and rendered in both catalog formats only when set. Two things surfaced during the work. First, the acceptance criteria were self-contradictory: "fully backward-compatible" and "invalid semver fails registration" cannot both hold, so this is recorded as a deliberate breaking change for skills carrying a non-semver `version` today. Second, YAML types the field before validation ever sees it — `1.0` is a float, `2024-01-15` a date — so non-string values get an error naming the coercion instead of a bare type mismatch. No new dependency: the semver.org regex is inlined rather than pulling a package in for one match. |
| HTTP error classification | Resilience | `agentskills-http` | **Implemented, awaiting release.** Every non-2xx mapped to `SkillNotFoundError`, so a `503` and a genuine `404` were indistinguishable. Now `404`/`410` → `SkillNotFoundError`, and `5xx`/`408`/`425`/`429`/timeouts/connection errors → a new `SkillUnavailableError` carrying `retry_after`, with bounded jittered-backoff retry that honours `Retry-After`. Also fixed a credential leak found during the work: chaining `httpx.HTTPStatusError` put the full request URL — query string included — into every traceback, exposing SAS tokens and signed-URL signatures. |
| Structured logging | Operability | all | **Implemented, awaiting release.** Outside one warning the SDK was silent, so retries, cache hits and registration outcomes were invisible in production. Everything now logs under one `agentskills.*` namespace via `get_logger(__name__)`, which rewrites the distribution prefix so `agentskills_http.static` becomes `agentskills.http.static` — plain `logging.getLogger(__name__)` produced names that did *not* descend from a common root, so a host could not raise the level on the library with one call. Only a `NullHandler` is attached. There is deliberately no `ERROR` level: failures raise, and logging them too would report the same event twice. `redact_url()` is the shared sanitiser for anything URL-shaped, lifted out of the HTTP provider's private `_describe()` so errors and logs cannot drift apart; headers are never logged at all, on the grounds that a redactor you must remember to call is a trap. |
| Coverage gate in CI | Project health | repo | `pytest-cov` with a floor, enforced in CI, badge in README. |
| Automated PyPI publish | Project health | repo | Replace manual `publish.ps1` runs with GitHub Actions **Trusted Publishing** (OIDC, no long-lived tokens), triggered by the release tag. |
| Agent Framework 1.x API rename | Correctness | `agentskills-agentframework`, `agentskills-mcp-server` | **Merged, awaiting release.** `agent-framework-core` 1.12.1 renamed `BaseContextProvider` to `ContextProvider`; our constraint `>=1.0.0rc3,<2.0` admitted it, so a fresh install raised `ImportError` on import. Masked locally because `poetry.lock` pinned 1.0.0rc3. Floor raised to `>=1.0`. |
| Python 3.14 support | Project health | all | **Merged, awaiting release.** Every package capped `python` at `<3.14`, so installs failed on current stable Python. Ceiling raised to `<4.0`; no dependency justified the old cap. |

---

## Next — v0.4 "Developer Experience"

Make authoring and validating skills a first-class workflow, and make third-party providers
provably correct.

| Item | Theme | Package(s) | Notes |
|---|---|---|---|
| `agentskills` CLI | DX | new `agentskills-cli` | `init` (scaffold a skill), `validate <path>` (spec check, exit non-zero on failure), `lint` (style/token-budget warnings), `inspect` (render catalog/metadata), `serve` (run the MCP server without writing config by hand). |
| Skill validation GitHub Action | DX | repo | Thin wrapper over `agentskills validate` so skill repos can gate PRs. Highest-leverage adoption lever — it puts the SDK in other people's CI. |
| Provider conformance test kit | Correctness | new `agentskills-testing` | A published pytest suite any third-party provider can run to prove it satisfies the `SkillProvider` contract (traversal safety, size limits, error types, resource listing). Turns the protocol into a real, testable interface. |
| Test doubles | DX | `agentskills-testing` | `InMemorySkillProvider` + fixtures so downstream users can unit-test agents without disk or network. |
| Registry-level discovery | DX | `agentskills-core` + providers | Optional `discover()` on providers, plus `registry.register_all(provider)`. Registering N skills currently requires knowing all N IDs up front. |
| Catalog filtering & budget | DX / Perf | `agentskills-core` | `get_skills_catalog(tags=..., include=..., max_chars=...)`. The catalog is injected into every system prompt; it must not grow without bound. |
| Skill evaluation harness | Agent effectiveness | `agentskills-testing` + CLI | `agentskills eval` — run a skill's test cases against a real model with and without the skill loaded, and report the delta. Skills are prompts, and today nobody measures whether one helps. Makes skill authoring an engineering activity instead of a matter of taste. |
| Foreign format adapters | Interoperability | new `agentskills-adapters` | Import `AGENTS.md`, `.github/copilot-instructions.md`, Cursor rules, and Claude skill folders as `Skill` objects. An import layer, not a spec fork — it attacks the empty-registry problem, which is the real adoption barrier. |
| Token cost reporting | DX | `agentskills-cli` | `agentskills inspect --cost` breaking down tokens by catalog entry, body section, and resource. Authors cannot budget what they cannot see. |
| Documentation site | Project health | repo | MkDocs Material with API reference, versioned per release. README is already carrying more than it should. |
| Architecture decision records | Project health | `docs/adr/` | Short ADRs for cross-package decisions (async model, caching strategy, error taxonomy, packaging). |

---

## Next — v0.5 "Agent Effectiveness"

Everything before this makes skills safe and cheap to ship. This milestone is about making them
**worth** shipping — the point where the SDK stops being a loader and starts changing how well the
agent performs.

| Item | Theme | Package(s) | Notes |
|---|---|---|---|
| Semantic skill selection | Agent effectiveness | new `agentskills-retrieval` | The catalog is injected on every turn, so prompt cost is linear in registered skills. Embed descriptions once, select top-k against the current turn, inject a handful. Descriptions are already written to be discriminative, so the corpus exists for free. Ships with a zero-dependency lexical default; embeddings are pluggable. Opt-in, and it must log its selection — this trades a deterministic prompt for a better one. |
| Section-level disclosure | Agent effectiveness | `agentskills-core` + integrations | `get_skill_body()` is all-or-nothing, so a thorough 4k-token skill is charged in full to use one section. Split the body by heading, return an outline plus `get_skill_section(skill_id, heading)`. Extends progressive disclosure one level inward rather than adding a new idea, and stops penalising well-written skills. |
| Stateful / session-aware disclosure | Agent effectiveness | `agentskills-agentframework` | Use the context provider's session `state` and `after_run` hook to track which skills the agent already loaded, prune the advertised catalog to the active domain, and inject resource-level tools only for loaded skills. Turns progressive disclosure into a framework-level behaviour rather than a prompt instruction. |
| Vision-native assets | Agent effectiveness | integrations | Once binary resources are safe (v0.3), stop stringifying them: hand images to multimodal models as native content. A skill can then carry an architecture diagram or a UI screenshot that the model actually sees. |
| Selection metadata | Correctness | `agentskills-core` | Optional `when_to_use` / `when_not_to_use` frontmatter. False activation is as damaging as non-activation, and a description alone carries no negative signal. Improves both LLM selection and retrieval ranking. Optional and backward-compatible per principle 1; push upstream. |
| Single-skill fast path | Performance | integrations | When exactly one skill is registered or selected, inject the body directly instead of advertising a tool and waiting for the agent to call it. Removes a full round-trip from the common single-purpose-agent case. |

---

## Later — v0.6 "Trust & Operability"

The enterprise story. This is the work that makes the SDK viable as the substrate for
[Agent Skills Hub](https://github.com/pratikxpanda/agentskills-hub).

| Item | Theme | Package(s) | Notes |
|---|---|---|---|
| Skill integrity & provenance | Trust | `agentskills-core` | Optional manifest with per-file SHA-256, verified on load. Then detached signature verification (Sigstore) and an "unverified skill" policy switch. Skills are code — this is the missing supply-chain control. |
| Content policy pipeline | Trust | `agentskills-core` | Pluggable `SkillPolicy` hooks that run before content enters agent context: reject, redact, or annotate. Ships with a heuristic prompt-injection scanner and a max-token guard; enterprises plug in their own. |
| `allowed-tools` enforcement | Trust | integrations | The field is validated but never enforced. Integrations should be able to constrain the agent's tool surface while a skill is active. |
| SSRF hardening | Trust | `agentskills-http` | Host allow/deny lists, private/link-local IP range blocking by default, DNS-rebinding-aware connection checks. `require_tls` alone is not an SSRF control. |
| Secret redaction | Trust | `agentskills-core`, `agentskills-http` | Central redaction helper applied to exception messages and log records so `Authorization` headers and SAS tokens never surface in tracebacks. |
| OpenTelemetry instrumentation | Operability | `agentskills-core` + providers | Spans for fetch/parse/validate, metrics for fetch latency, cache hit ratio, and payload size. Optional dependency, no-op when OTel is absent. |
| Skill usage telemetry hooks | Operability | `agentskills-core` | Callback protocol emitting "skill X disclosed at level Y". Answers the question every platform team asks: *which skills are actually being used?* Feeds Hub analytics directly. |
| Startup health check | Resilience | `agentskills-core` | `registry.health()` verifying every provider is reachable and every skill parses, at boot. A misconfigured provider should fail deployment, not fail silently mid-conversation. |
| Serve-stale on provider failure | Resilience | providers | If a refresh fails but cached content exists, serve the stale copy and flag it rather than failing the agent turn. A registry outage should degrade the agent, not break it. Builds on v0.3 caching and error classification. |

---

## Later — v0.7 "Ecosystem"

Breadth, once the core contracts are stable enough that each new package is cheap to add.

| Item | Theme | Notes |
|---|---|---|
| Skills as MCP prompts | Interoperability | The MCP server exposes skills as tools only. Many clients surface *prompts* as slash commands, so the same registry becomes user-invocable in Claude Desktop, VS Code, and others for very little work. |
| Git provider | Ecosystem | Most skills live in Git repos. Clone/fetch with ref or commit pinning, sparse checkout, local cache. Likely the single most requested provider. |
| Object storage provider | Ecosystem | S3 / Azure Blob / GCS via a common abstraction, with native credential chains instead of hand-rolled headers. |
| OCI artifact provider | Ecosystem | Skills as OCI artifacts in any container registry — inherits existing signing, replication, and RBAC infrastructure. Pairs naturally with the integrity work in v0.5. |
| Database provider | Ecosystem | Reference implementation over SQL for teams storing skills in an existing system of record. |
| OpenAI Agents SDK integration | Ecosystem | Notable gap in the current integration matrix. |
| Additional framework adapters | Ecosystem | Pydantic AI, Semantic Kernel, LlamaIndex, CrewAI. Prioritize by inbound demand rather than building all of them speculatively. |
| Node/TypeScript port | Ecosystem | Large commitment. Only if there is clear pull — the MCP server already serves TS agents today, which may be sufficient. |

---

## v1.0 — Stability

| Item | Notes |
|---|---|
| API freeze | Public surface documented and frozen; anything not documented is explicitly private. |
| Compatibility policy | SemVer commitments, a written deprecation policy with a minimum support window, and coordinated cross-package version guarantees. |
| Release automation end-to-end | Changelog generation, signed artifacts with build provenance/attestations, automated publish on tag. |
| Hub interoperability | The SDK contracts the Hub depends on (versioning, integrity, telemetry, MCP gateway composition) are stable and documented. |

---

## Explicit Non-Goals

Stating these prevents recurring proposals and scope creep.

- **Executing skill scripts.** The SDK retrieves scripts; it does not run them. Sandboxed
  execution is the host application's responsibility. We will document the hazard, not own it.
- **Authoring or hosting UI.** That is [Agent Skills Hub](https://github.com/pratikxpanda/agentskills-hub)'s job.
- **Authentication and authorization.** Providers accept caller-supplied credentials. The SDK
  is not an identity or policy system.
- **Being an agent framework.** We integrate with frameworks; we do not compete with them.
- **Forking the skill format.** Divergence from the open spec is a last resort.

---

## How We Plan Work

| Artifact | Purpose |
|---|---|
| **This roadmap** | Direction and sequencing. Reviewed at the start of each minor version. No dates. |
| **GitHub Milestones** | One per minor version (`v0.3`, `v0.4`, …). An item is committed when it has an issue in a milestone. |
| **GitHub Issues** | The single unit of work. Status, assignment, discussion, and linked PRs. Labelled by `theme:*`, `package:*`, `type:*`, and `good-first-issue`. |
| **[docs/issues/](./issues/)** | The durable specification behind each roadmap item, one file per milestone. Filed issues link back here instead of duplicating the text; shipped items stay for the record. |
| **GitHub Project board** | Now / Next / Later / Done view across issues, linked from the README. |
| **[docs/adr/](./adr/)** | Short, immutable records of decisions already made and their trade-offs. Written when a decision is hard to reverse or likely to be questioned later. |

**Contributing to the roadmap:** open a GitHub Discussion for an idea, or an issue for
something concrete. Changes to a public contract should be agreed on the issue before a PR
is opened. Items marked `good-first-issue` are the recommended entry point.
