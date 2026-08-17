# Agent Skills SDK — Roadmap

> Public roadmap for the [Agent Skills SDK](index.md). Themes and ordering, not dates.

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

## Shipped — v0.3 "Foundations"

Released 2026-07-31. Closed the highest-severity correctness and performance gaps before the API
surface widened. Specifications and implementation notes: [docs/issues/v0.3.md](./issues/v0.3.md).

Two changes are breaking for existing users, which a minor version is entitled to pre-1.0 but
which the release notes should state plainly: `SkillProvider` gained resource discovery, and a
skill carrying an invalid `version` in its frontmatter now fails registration instead of being
registered with a warning.

| Item | Theme | Package(s) | Notes |
|---|---|---|---|
| Provider content caching | Performance | `agentskills-fs`, `agentskills-http` | A single skill's `SKILL.md` was fetched up to 5x per session — twice during registration (`validate_skill()` calls `get_body()` and `get_metadata()` independently), once per catalog build, and again on each tool call. Now cached per provider instance with an explicit `invalidate()`. HTTP revalidation via `ETag` / `Last-Modified` is opt-in (`revalidate=True`) rather than default, since a conditional request per access defeats the point for the common static-host case. |
| Concurrent catalog build | Performance | `agentskills-core` | `get_skills_catalog()` fetched metadata serially. Now fans out with `asyncio.gather` under a bounded semaphore (`SkillRegistry(catalog_concurrency=8)`); output ordering is unchanged. |
| Non-blocking filesystem I/O | Performance | `agentskills-fs` | The provider was `async` but read synchronously, blocking the event loop. Path resolution, stat and read now run in a worker thread via `asyncio.to_thread`. |
| Resource discovery API | Correctness | `agentskills-core` + providers | Agents had no way to learn which references/scripts/assets exist; discovery depended entirely on SKILL.md prose. `list_resources(skill_id)` is now an *optional* provider capability paired with a `supports_resource_listing` flag ([ADR 0002](adr/0002-optional-provider-capabilities.md)). The default implementation raises `ResourceListingNotSupportedError` rather than returning `{}`, so "cannot enumerate" is never mistaken for "has no resources". Filesystem enumerates directly; HTTP requires an opt-in per-skill `index.json`, which also gives the supply-chain work a natural home for integrity hashes. |
| Binary-safe resources | Correctness | `agentskills-core` + all integrations | All three integrations decoded provider bytes with `.decode("utf-8", errors="replace")`, silently destroying images, PDFs, and archives. A shared `encode_resource_content()` now returns valid UTF-8 verbatim and wraps everything else in a base64 JSON envelope. Using MCP's native binary content blocks instead of a JSON string remains a follow-up. |
| Optional `version` frontmatter | Correctness | `agentskills-core` | Skills had no version, so nothing could be pinned, compared, or checked for drift. `version` is now optional, validated as semver when present, returned by `get_metadata()`, and rendered in both catalog formats only when set. Two things surfaced during the work. First, the acceptance criteria were self-contradictory: "fully backward-compatible" and "invalid semver fails registration" cannot both hold, so this is recorded as a deliberate breaking change for skills carrying a non-semver `version` today. Second, YAML types the field before validation ever sees it — `1.0` is a float, `2024-01-15` a date — so non-string values get an error naming the coercion instead of a bare type mismatch. No new dependency: the semver.org regex is inlined rather than pulling a package in for one match. |
| HTTP error classification | Resilience | `agentskills-http` | Every non-2xx mapped to `SkillNotFoundError`, so a `503` and a genuine `404` were indistinguishable. Now `404`/`410` → `SkillNotFoundError`, and `5xx`/`408`/`425`/`429`/timeouts/connection errors → a new `SkillUnavailableError` carrying `retry_after`, with bounded jittered-backoff retry that honours `Retry-After`. Also fixed a credential leak found during the work: chaining `httpx.HTTPStatusError` put the full request URL — query string included — into every traceback, exposing SAS tokens and signed-URL signatures. |
| Structured logging | Operability | all | Outside one warning the SDK was silent, so retries, cache hits and registration outcomes were invisible in production. Everything now logs under one `agentskills.*` namespace via `get_logger(__name__)`, which rewrites the distribution prefix so `agentskills_http.static` becomes `agentskills.http.static` — plain `logging.getLogger(__name__)` produced names that did *not* descend from a common root, so a host could not raise the level on the library with one call. Only a `NullHandler` is attached. There is deliberately no `ERROR` level: failures raise, and logging them too would report the same event twice. `redact_url()` is the shared sanitiser for anything URL-shaped, lifted out of the HTTP provider's private `_describe()` so errors and logs cannot drift apart; headers are never logged at all, on the grounds that a redactor you must remember to call is a trap. |
| Coverage gate in CI | Project health | repo | `pytest-cov` was not even a dev dependency. Coverage is now measured by *import name* rather than by path — measuring `packages/` counted the test files, which are trivially covered by being run, and inflated the figure from a real 96% to a meaningless 99%. Floors are enforced twice: an aggregate `fail_under` that `coverage report` applies on its own, and a per-package floor in `scripts/dev.py`, because an aggregate alone lets one package rot behind the others. Demonstrated: five uncovered statements in core drop that package from 99% to 97% while the aggregate never moves. Both sets start at the measured value and ratchet. The badge states the enforced floor (`coverage ≥96%`) rather than a per-commit number, since a live figure needs a third-party account the project does not have. |
| Automated PyPI publish | Project health | repo | Releasing was six `poetry publish` runs from a workstation holding a long-lived PyPI token. Now tag-triggered, with **Trusted Publishing** (OIDC) so no token exists in the repo, in Actions secrets, or on a laptop, and PEP 740 provenance attestations on every artifact. Only a bare `vX.Y.Z` tag reaches PyPI; every other tag shape falls through to TestPyPI, so a malformed tag cannot burn a real version. A guard refuses to build unless all six packages agree on the version *and* match the tag. One environment approval gates the whole release rather than one per package, and re-running a half-finished release is safe. The GitHub Release moved to the end of the same workflow, because it was previously created on tag push regardless of whether publishing succeeded. |
| Agent Framework 1.x API rename | Correctness | `agentskills-agentframework`, `agentskills-mcp-server` | `agent-framework-core` 1.12.1 renamed `BaseContextProvider` to `ContextProvider`; our constraint `>=1.0.0rc3,<2.0` admitted it, so a fresh install raised `ImportError` on import. Masked locally because `poetry.lock` pinned 1.0.0rc3. Floor raised to `>=1.0`. |
| Python 3.14 support | Project health | all | Every package capped `python` at `<3.14`, so installs failed on current stable Python. Ceiling raised to `<4.0`; no dependency justified the old cap. |

---

## Shipped — v0.4 "Developer Experience"

Released 2026-08-17. Made authoring and validating skills a first-class workflow, and third-party
providers provably correct. Specifications and implementation notes:
[docs/issues/v0.4.md](./issues/v0.4.md).

Three new distributions ship with this milestone — `agentskills-tools`, `agentskills-testing` and
`agentskills-adapters` — bringing the lockstep-versioned set to nine. Nothing is breaking for
existing users.

| Item | Theme | Package(s) | Notes |
|---|---|---|---|
| `agentskills` CLI | DX | new `agentskills-tools` | `init` (scaffold a skill), `validate <path>` (spec check, exit non-zero on failure), `lint` (style/token-budget warnings), `inspect` (render catalog/metadata), `serve` (run the MCP server without writing config by hand). Separate package and stdlib `argparse` so the validation Action inherits no dependencies; `serve` is an optional extra. |
| Skill validation GitHub Action | DX | repo | Composite action at `actions/validate` wrapping `agentskills validate` and `lint`. Findings land on the pull request diff via the CLI's own `--format github`, so the annotation logic is unit-tested in the package rather than in a script beside the workflow. Highest-leverage adoption lever — it puts the SDK in other people's CI. |
| Provider conformance test kit | Correctness | new `agentskills-testing` | `ProviderConformanceSuite` — subclass it, supply a `provider` fixture, and pytest runs the whole contract against your implementation: error types, traversal rejection, `bytes` not `str`, metadata that is neither shared nor carrying the body, and a `list_resources()` that agrees with the flag callers branch on. Size limits sit in an opt-in `ContentLimitConformanceSuite`, since an in-memory provider has no external source to bound. Its first run found that `agentskills-http` raised a plain `ValueError` for traversal where `agentskills-fs` raised `SkillNotFoundError` — an ABC cannot catch that, which is the argument for the kit. |
| Test doubles | DX | `agentskills-testing` | `InMemorySkillProvider` — a real provider backed by a dict that passes the suite above — plus `build_skill()` and pytest fixtures registered via an entry point. Replaced the four duplicated `_mock_provider` helpers in this repo, which had been raising `KeyError` where a real provider raises `ResourceNotFoundError`. |
| Registry-level discovery | DX | `agentskills-core` + providers | Optional `discover()` on providers, following ADR 0002, plus `registry.register_all(provider)` — atomic, and reporting every validation failure at once rather than the first. The filesystem provider enumerates subdirectories holding a `SKILL.md`; the HTTP provider reads a root `index.json`, the same filename and shape as the per-skill resource manifest one level up. Registering N skills no longer requires knowing all N IDs up front. |
| Catalog filtering & budget | DX / Perf | `agentskills-core` | `get_skills_catalog(tags=…, include=…, exclude=…, max_chars=…)`. Tags come from the spec's free-form `metadata` mapping rather than a new top-level field, so nothing has to be defended upstream. The ID filters run before any metadata is fetched, so narrowing a large registry costs proportionally fewer provider round-trips. `max_chars` drops whole entries from the end and says so — `truncated`/`shown`/`total` on the XML root, a closing note in Markdown — because a catalog that shrinks silently makes agent behaviour non-reproducible. |
| Skill evaluation harness | Agent effectiveness | `agentskills-tools` | `agentskills eval` runs each case in a skill's `evals/` folder twice — once with the skill's body in the system prompt, once without — and reports the delta, because absolute pass rates mostly measure the model while the difference isolates the skill. Assertions are deterministic (`contains`, `not_contains`, `regex`) or judged by a declared model; `repeat`/`threshold` make sampling noise visible instead of letting one lucky sample pass as a measurement. Model access is a one-method protocol resolved from a dotted path, so no provider SDK is a dependency anywhere. Completions cache by model, prompts, and repeat index, so tightening an expectation re-grades answers already bought. Landed in the CLI rather than `agentskills-testing`: the requirement is that it *never* runs in the default `pytest` run, which makes it a command, not a test kit. |
| Foreign format adapters | Interoperability | new `agentskills-adapters` | `agentskills-adapters` imports `AGENTS.md`, `.github/copilot-instructions.md`, Cursor `.mdc` rules, and Claude skill folders as ordinary `Skill` objects. Missing descriptions become explicit synthesized catalog text, Cursor `globs` stay in native metadata, and `agentskills init --from` writes a validated editable `SKILL.md`. It is an import layer, not a spec fork: a migration path for existing instructions rather than a second runtime model. |
| Token cost reporting | DX | `agentskills-tools` | `agentskills inspect --cost` splits a skill into what is charged on every turn (the catalog entry), what is charged per load (the body, broken down by section), and what is charged only if the agent reads it (each resource). Authors reliably budget the body while ignoring a description that costs a hundred tokens a turn forever, so `--budget` and `--turn-budget` gate the two halves separately — one threshold would be dominated by the body and hide exactly the number the feature exists to surface. Sections do not nest, so the parts sum to the whole, which is the only property that makes a breakdown checkable. `tiktoken` is used when importable and a character heuristic otherwise, but the counter is named in every report and `--tokenizer tiktoken` refuses to fall back: a budget gate whose arithmetic depends on what happens to be installed is worse than no gate. It stays out of the dependency list — a compiled wheel that downloads its vocabulary on first use is a poor trade for a tool whose main job is reading YAML in CI. |
| Documentation site | Project health | repo | Added a MkDocs Material site with a docs-first navigation (getting started, concepts, one page per package, roadmap and ADRs) and API pages generated via `mkdocstrings` from existing docstrings. New docs workflow builds the site in CI (`mkdocs build --strict`) and deploys versioned docs on published releases via `mike`, with `latest` as the default alias. Root README was reduced to overview + quick start + links. |
| Architecture decision records | Project health | `docs/adr/` | Added an ADR index and template plus backfilled records for six cross-package decisions: fully async provider interface, multi-package lockstep versioning, provider caching/invalidation, exception taxonomy (`not found` vs `unavailable`), binary resource envelope, and logging namespace/severity conventions. Each ADR links back to the issue section where the decision was made so future reversals are explicit rather than accidental. |
| Simplify the publish workflow | Project health | repo | Dropped the TestPyPI dry-run path. Pending trusted publishers must be uniquely identifiable by their claims, and all seven distributions share owner, repo, workflow and environment — so only one pending publisher can exist at a time, and bootstrapping them on a fresh index takes one sequential publish round each. The result was a dry run configured for one package out of seven, which failed in a way that looked like a real problem. An unrecognised tag now fails the run instead of falling through to another index, `workflow_dispatch` builds without uploading, and pre-release tags go to PyPI, which handles them natively. |

---

## Now — v0.5 "Agent Effectiveness"

Everything before this makes skills safe and cheap to ship. This milestone is about making them
**worth** shipping — the point where the SDK stops being a loader and starts changing how well the
agent performs.

The first two items change contracts the rest build on — the frontmatter schema and the shape of a
body fetch — so the table is ordered by dependency rather than by value. Specifications:
[docs/issues/v0.5.md](./issues/v0.5.md).

| Item | Theme | Package(s) | Notes |
|---|---|---|---|
| Selection metadata | Correctness | `agentskills-core` | Optional `when_to_use` / `when_not_to_use` frontmatter. False activation is as damaging as non-activation, and a description alone carries no negative signal. Improves both LLM selection and retrieval ranking. Optional and backward-compatible per principle 1; push upstream. |
| Section-level disclosure | Agent effectiveness | `agentskills-core` + integrations | `get_skill_body()` is all-or-nothing, so a thorough 4k-token skill is charged in full to use one section. Split the body by heading, return an outline plus `get_skill_section(skill_id, heading)`. Extends progressive disclosure one level inward rather than adding a new idea, and stops penalising well-written skills. |
| Semantic skill selection | Agent effectiveness | new `agentskills-retrieval` | The catalog is injected on every turn, so prompt cost is linear in registered skills. Embed descriptions once, select top-k against the current turn, inject a handful. Descriptions are already written to be discriminative, so the corpus exists for free. Ships with a zero-dependency lexical default; embeddings are pluggable. Opt-in, and it must log its selection — this trades a deterministic prompt for a better one. |
| Stateful / session-aware disclosure | Agent effectiveness | `agentskills-agentframework` | Use the context provider's session `state` and `after_run` hook to track which skills the agent already loaded, prune the advertised catalog to the active domain, and inject resource-level tools only for loaded skills. Turns progressive disclosure into a framework-level behaviour rather than a prompt instruction. |
| Single-skill fast path | Performance | integrations | When exactly one skill is registered or selected, inject the body directly instead of advertising a tool and waiting for the agent to call it. Removes a full round-trip from the common single-purpose-agent case. |
| Vision-native assets | Agent effectiveness | integrations | Once binary resources are safe (v0.3), stop stringifying them: hand images to multimodal models as native content. A skill can then carry an architecture diagram or a UI screenshot that the model actually sees. |

---

## Next — v0.6 "Trust & Operability"

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
