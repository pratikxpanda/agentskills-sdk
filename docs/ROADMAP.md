---
title: Agent Skills SDK Roadmap
description: MCP-first priorities, the native-only v0.7 line, and future SDK capabilities.
---

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
    MCP support are optional installs and never leak into core.
5. **MCP-first interoperability.** MCP is the maintained integration boundary. Frameworks
    connect through their own MCP clients, not SDK-owned native adapters. Reusable skill
    behaviour belongs in core or retrieval, not in a framework lifecycle hook.

## Direction From v0.6.0

v0.6.0 establishes standards-aligned skill delivery over MCP. The v0.7 development
line builds production trust and operability on that contract. It is native-only:
the v0.6 framework integrations and legacy MCP delivery are removed. Published
v0.6 wheels are unchanged.

### Official MCP Skills Support

Checked 2026-10-05: MCP has an official, optional
[Skills extension](https://modelcontextprotocol.io/extensions/skills/overview),
`io.modelcontextprotocol/skills`. [SEP-2640](https://modelcontextprotocol.io/seps/2640-skills-extension)
is Final. The [published extension specification](https://github.com/modelcontextprotocol/ext-skills/blob/main/specification/stable/skills.mdx)
is authoritative for current requirements, rather than the historical SEP text. The current
base protocol revision is [2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28).
The [client support matrix](https://modelcontextprotocol.io/extensions/client-matrix) still shows
uneven adoption, so ordinary MCP connectivity is not proof of Skills extension support.

The Agent Skills specification defines the file format. The MCP extension defines its
discovery and transport binding. Alignment means:

- Declare the Resources capability and Skills extension through the supported protocol's
   capability mechanism. For 2026-07-28, this includes `server/discover` and per-request metadata.
- Implement paginated `skills/list` and direct `skills/get`. Entries carry the full,
   unchanged frontmatter and a complete file manifest with raw-byte SHA-256 digests and sizes,
   or the explicit `"dynamic"` marker where stable content cannot be promised.
- Serve the full `SKILL.md`, including frontmatter, and supporting files through
   `resources/read`, conventionally at `skill://<skill-path>/SKILL.md` and sibling URIs.
   Preserve arbitrary supporting directories, relative references, and native text/blob content.
- Follow the current result, cache, error, and pagination contracts. Gate optional
   `resources/directory/read` behind `directoryRead`, and account for the extension's
   interoperability limits of 512 files and 16 MiB per skill.
- Keep discovery metadata-only on the client. Reading a resource is not skill activation.
   Hosts own selection, approval, context injection, and execution permissions. Skills are
   identified by originating server plus URI, not by name alone.

The v0.6 `get_skill_*` tools and `skills://catalog/*` resources were a compatibility
surface, not this extension, and are removed in v0.7. MCP prompts may provide user-invoked shortcuts, but do not
substitute for native skill discovery. Section disclosure and retrieval remain useful SDK
features, without becoming proprietary requirements for reading a standards-compliant skill.

### Native-Only Delivery

Decision on 2026-10-06: v0.7 is native-Skills-only. The maintainer explicitly
accepted removal of the v0.6 framework packages, the Agent Framework bridge, the
legacy tools and catalog resources, and MCP 1.x support rather than waiting for
native framework parity. Retired source is deleted from the active tree, with no
`archived/` directory. The v0.6.0 tag, wheels, and versioned docs preserve history.
See the [breaking-change guide](mcp-migration.md) for pinning guidance.

`agentskills-adapters` imports instruction formats and remains supported, as do the
framework-neutral core, providers, retrieval, testing, and CLI. No new first-party
framework adapters are planned.

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
| **MCP interoperability** | One standards-aligned delivery path reaches multiple hosts without maintaining a native adapter for each framework. |
| **Distribution** | Reproducible, portable skill sources matter more than a long list of speculative providers. |
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

## Shipped — v0.5 "Agent Effectiveness"

Released 2026-08-19. Everything before this makes skills safe and cheap to ship. This milestone is
about making them **worth** shipping — the point where the SDK stops being a loader and starts
changing how well the agent performs. Specifications and implementation notes:
[docs/issues/v0.5.md](./issues/v0.5.md).

One new distribution ships with this milestone — `agentskills-retrieval` — bringing the
lockstep-versioned set to ten. Nothing is breaking for existing users.

The first two items changed contracts the rest build on — the frontmatter schema and the shape of a
body fetch — so the table is ordered by dependency rather than by value.

| Item | Theme | Package(s) | Notes |
|---|---|---|---|
| Selection metadata | Correctness | `agentskills-core` | Optional `when_to_use` / `when_not_to_use` frontmatter, each a list of at most five 200-character entries. False activation is as damaging as non-activation, and a description alone carries no negative signal. Rendered in both catalog formats and omitted when absent; `get_skills_catalog(selection_hints=False)` trades the accuracy back for tokens. Optional and backward-compatible per principle 1; still to be pushed upstream. |
| Section-level disclosure | Agent effectiveness | `agentskills-core` + integrations | `get_skill_body()` is all-or-nothing, so a thorough 4k-token skill is charged in full to use one section. Split the body by heading, return an outline plus `get_skill_section(skill_id, heading)`. Extends progressive disclosure one level inward rather than adding a new idea, and stops penalising well-written skills. |
| Semantic skill selection | Agent effectiveness | new `agentskills-retrieval` | The catalog is injected on every turn, so prompt cost is linear in registered skills. Embed descriptions once, select top-k against the current turn, inject a handful. Descriptions are already written to be discriminative, so the corpus exists for free. Ships with a zero-dependency lexical default; embeddings are pluggable. Opt-in, and it must log its selection — this trades a deterministic prompt for a better one. |
| Stateful / session-aware disclosure | Agent effectiveness | `agentskills-agentframework` | The provider re-injected the whole catalog on every turn regardless of what the agent had already read. `after_run` now records full-body loads in session `state`, and later turns prune those entries down to a one-line reminder — caching saves provider I/O, but pruning is what makes turn N+1 cheaper. Declines to prune when the reminder would cost more than the entries, and never prunes to an empty catalog. Topic-based pruning was left out: that is semantic selection again, and it belongs in `agentskills-retrieval`. |
| Single-skill fast path | Performance | `agentskills-core` + integrations | A catalog exists to let a model choose; with one skill there is nothing to choose, so `resolve_fast_path()` inlines the body and drops the catalog, the usage instructions and the four body-access tools, removing a whole model round trip. Triggers on the *effective* set, so a registry narrowed to one by retrieval qualifies too. The token ceiling defaults to the size below which the fast path wins at any conversation length rather than to a guess; measured saving is 38-49% for a small skill. Resource tools stay — a skill carrying a 2 MB dataset must not have it inlined because the skill count happened to be one. |
| Vision-native assets | Agent effectiveness | `agentskills-core` + integrations | A base64 envelope is the right answer for an opaque binary and the wrong one for a diagram — the model got a wall of characters where a picture was. One classifier in core decides which is which; the three integrations differ only in how they wrap the result. Detection reads magic bytes before the filename, because a name is a claim and bytes are evidence. Native delivery is opt-in via `vision=True`, since handing an image to a text-only model is an API error rather than a worse answer, and no integration can ask a model whether it can see. Images get their own 5 MiB ceiling: the 64 KiB cap tracks tokens, and a native image is billed by tile count instead. PDF and SVG are excluded, and everything non-renderable keeps the v0.3 envelope unchanged. |

---

## v0.6 "MCP-First Skills"

Shipped as v0.6.0. The descriptions below record that release, including
compatibility surfaces subsequently removed in v0.7 development.

v0.6.0 makes the official Skills extension the primary integration path. The work
centers on the wire contract and migration safety. Protocol-required integrity is
included, not postponed to the broader trust work in v0.7.

| Item | Theme | Package(s) | Notes |
| --- | --- | --- | --- |
| Native adapter deprecation and migration | Interoperability | native integrations, MCP, docs | Deprecate the native framework adapters and provide examples using their upstream MCP clients. Inventory framework-only behaviour and publish supported replacements or explicit gaps before removing anything. |
| Official Skills extension and protocol baseline | Correctness | `agentskills-mcp-server` | Select an official Python MCP SDK release with the required protocol/extension support. Implement capability declaration, `skills/list`, `skills/get`, required request metadata and result/cache fields, pagination, and specified errors. Record supported protocol and extension revisions. An empty or partial listing must not prevent direct lookup of a served skill. |
| Lossless skill resources and manifests | Correctness / Trust | core, providers, MCP | Add the provider capabilities needed to serve complete raw `SKILL.md` content and every supporting file, including nonstandard and nested directories. Preserve all frontmatter fields, resolve registry aliases to conforming URI paths, and publish complete byte-accurate manifests. Retain coherent snapshots so files cannot drift from advertised digests. Do not pass canonical reads through body-only, section, image-conversion, or binary-omission paths. Reserve `"dynamic"` for genuinely dynamic content, not as a workaround for missing enumeration. |
| Legacy MCP compatibility and host boundaries | Interoperability | MCP, core, retrieval | Keep existing tools and `skills://` resources as an explicit compatibility mode during adoption. Do not silently rewrite their URIs or claim feature parity. Native Skills mode must not eagerly inline a lone skill at discovery or connection time. Keep selection, consent, session/context tracking, and `allowed-tools` grants host-owned. Avoid duplicate catalog injection when the host already manages skills. |
| MCP conformance and client compatibility matrix | Correctness | `agentskills-testing`, MCP tests, examples | Exercise real protocol round trips over stdio and Streamable HTTP, using upstream conformance scenarios where available. Cover pagination, direct lookup, exact frontmatter/bytes, digest drift, binary files, traversal, nested skills, unsupported capabilities, and legacy clients. Publish tested client versions and distinguish ordinary tools/resources support from full Skills support. This is a release gate, not an unverified "any client" promise. |
| Skill discovery and delivery benchmarks | Agent effectiveness / Performance | retrieval, tools, MCP | Measure selection precision/recall including no-match cases, metadata tokens, bytes read, tool/model round trips, and latency against the v0.5 path. Exercise small and large catalogs. Keep optional ranking separate from standards-based enumeration and preserve direct lookup. Prove discovery does not prefetch skill files into clients. |
| MCP inspection and deployment diagnostics | DX / Resilience | `agentskills-tools`, MCP | Extend inspect/serve diagnostics to report protocol capabilities, canonical skill URIs, manifest consistency, size-limit violations, provider readiness, and actionable client fallback guidance. Keep local stdio and remote Streamable HTTP recipes, with secure transport and authentication boundaries stated explicitly. |

v0.6 is complete when a conforming client can discover, verify, and progressively read a skill
without SDK-specific tools, and existing MCP users retain a tested migration path. Ship any
security fixes required for that path immediately rather than waiting for v0.7.

Implementation progress: core, filesystem, and opted-in HTTP providers now expose
complete original file access. Core can capture bounded immutable file sets with
SHA-256 digests and detect ordinary source drift during capture. Native manifests
preserve JSON-compatible frontmatter and complete file sets. An opt-in SDK 2.2+
server now implements the 2026-07-28 Skills wire contract, including pagination,
direct lookup, canonical original-byte reads, aliases, and explicit nested publication.
Directory reads remain unadvertised because empty-directory enumeration is unavailable.

Native framework entry points now emit caller-attributed deprecation warnings.
The [migration guide](mcp-migration.md) records maintenance-only status, the full
minor-release window, release-note guidance, and feature gaps. Model-free
filesystem examples exercise LangChain's upstream MCP adapter and Agent Framework's
MCPStdioTool against a separate SDK 2 server. No APIs or packages have been removed.

Native inspection now reports canonical manifests, original-byte digests and
sizes, protocol requirements, and local size-limit failures. Both CLI entry points
support publication preflight without listening, and the tools CLI can serve
native Skills directly. Config-driven preflight checks provider readiness and
closes its provider clients. Reports distinguish local construction from live
transport, authentication, and host verification. Remote HTTP deployment controls
remain explicit operational requirements, not a certification from preflight.

The [discovery and delivery benchmark](mcp-benchmarks.md) now measures the
native and retained v0.5-style workflows across small and large synthetic
catalogs. It separates optional lexical ranking, source snapshot reads, client
resource reads, token estimates, result bytes, and in-process timings. A real
request observer checks zero native discovery prefetch. Synthetic scores and
local timings do not certify production accuracy, model costs, or remote hosts.

The legacy server now supports MCP SDK 1.x and 2.2+ in the 2.x line, with a
dedicated modern-SDK CI job and real legacy stdio round trips across both SDK
directions in isolated environments. Native delivery is tested with the official
SDK client in-process, over stdio, and through a real loopback Streamable HTTP
listener. Older clients can read native resources but cannot invoke native
discovery. The MCP package publishes the tested client matrix. The pinned mcpc
0.7.0 client additionally verifies native direct lookup, paginated discovery,
aliases, and exact instructions, reference, and binary delivery over stdio.
The [v0.6 acceptance checklist](issues/v0.6.md) records the seven completed
implementation areas and the release verification requirements.

Production TLS, authentication, and gateway deployment validation is explicitly
deferred beyond v0.6 by the maintainer's 2026-10-06 scope decision. It is not a
passed gate or a production certification. Host selection, approval, context
injection, and execution policy remain host-owned. Local transport and client
checks do not certify those behaviors.

---

## Next: v0.7 "Trust & Operability"

Build production controls on the native-only MCP contract. Retirement is the
first implementation cluster and follows the explicit decision above.
Server-provided hashes establish consistency, not publisher trust. v0.7 is not
released. The controls below are implemented in the development tree. See the
[trust and operability guide](trust-and-operability.md) for contracts, tested
failure cases, and deployment responsibilities. Local tests do not certify
production identity infrastructure, TLS gateways, or host approval behavior.

| Item | Theme | Package(s) | Notes |
| --- | --- | --- | --- |
| Native-only retirement | Project health | integrations, release tooling, docs | Implemented in the development tree: remove the two native packages, Agent Framework bridge/extra, legacy MCP server, and MCP 1.x support. Eight maintained distributions remain. Preserve v0.6.0 artifacts and document the accepted loss of verified framework-client migration paths. No in-tree source archive. |
| Provenance and verified-content policy | Trust | core, providers | Build on v0.6 manifests with detached signature verification, trusted-publisher policy, and immutable content/version pinning. Keep unsigned, dynamically generated, and verified content distinguishable. Do not imply that a matching server-supplied digest establishes authorship or safety. |
| Content policy and host approval contract | Trust | core, MCP, docs | Add pluggable reject/redact/annotate hooks and token limits. Treat injection heuristics as advisory, not a security boundary. Server-side transformations must precede manifest generation. Document host duties for origin visibility, content-bound approvals, nested-skill consent, and permission grants. An MCP server cannot enforce another host's `allowed-tools` or sandbox. |
| Remote access hardening and secret redaction | Trust | HTTP, MCP, core | Cover outbound SSRF controls, redirect and DNS-rebinding checks, configurable private-network access, timeouts, and size limits. Cover inbound HTTP origin/host validation and integration with MCP authorization supplied by the deployment. Never pass client bearer tokens through to upstream providers. Redact credentials consistently from failures and diagnostics. |
| OpenTelemetry and disclosure events | Operability | core, providers, MCP | Optional spans and metrics for discovery, lookup, fetch, verification, cache hit rate, bytes, and latency. Emit privacy-preserving disclosure hooks with origin and content revision, not bodies or secrets. Distinguish server reads from actual host activation or task success. |
| Health checks and controlled refresh | Resilience | core, providers, MCP | Validate readiness before serving. Refresh registry metadata and manifests atomically, with cache scopes and TTLs appropriate to the negotiated protocol. Keep authorization-sensitive catalogs isolated and make changed or removed content observable. |
| Verified stale-cache policy | Resilience / Trust | providers, MCP | Opt-in, bounded-age stale serving for provider outages only. Serve a coherent previously verified snapshot with its matching manifest. Never downgrade on verification failure, revoked access, or known content removal. Make stale status observable without weakening host approval rules. |

---

## Later: v0.8 "Portable Distribution"

Expand sources and composition after MCP interoperability is proven. These are candidates,
ordered by expected value rather than a commitment to add every provider.

| Item | Theme | Notes |
| --- | --- | --- |
| Git provider with reproducible resolution | Distribution | Resolve refs to immutable commits, support subdirectory selection and a bounded local cache, and record origin and content digests. Do not run repository hooks or skill scripts. This is the first additional provider priority. |
| Skill lockfile and offline verification | Trust / DX | Record source, resolved revision, and per-file digests so CI and agents use the same content. Add drift detection and explicit update/rollback workflows. Reuse extension manifests rather than inventing a second skill format. This is local tooling, not an archive transport extension. |
| Framework-neutral MCP consumption and composition | Interoperability | Assess an optional MCP-backed provider/client helper using the official client SDK. Preserve originating server plus URI, on-demand reads, verification, cache isolation, and caller-owned approval. Avoid eager `register_all` content validation on discovery and prevent identity loss or loops when composing servers. No framework lifecycle adapters. |
| Object storage and OCI sources | Distribution | Add only with demonstrated demand. Object stores should reuse native credential chains. OCI should reuse existing artifact signing and registry controls. Both must preserve the same manifest and progressive-disclosure contracts. |
| Optional MCP prompt shortcuts | DX | User-invoked workflows for hosts that support prompts. Add only where they improve a tested workflow, without replacing Skills discovery or bypassing approval and provenance. |

SQL providers and a Node/TypeScript port are deferred pending demand that MCP cannot satisfy.
New OpenAI Agents SDK, Pydantic AI, Semantic Kernel, LlamaIndex, and CrewAI native adapters are
removed from the roadmap. Examples using those frameworks' MCP clients remain in scope.

---

## v1.0 — Stability

| Item | Notes |
|---|---|
| API freeze | Public surface documented and frozen. Anything not documented is explicitly private. |
| Compatibility policy | SemVer commitments, a written deprecation policy with a minimum support window, and coordinated version guarantees for maintained packages. Publish supported MCP protocol/extension revisions. |
| Release automation end-to-end | Preserve existing Trusted Publishing and attestations. Complete changelog automation and validate the reduced package inventory and reproducible release process. |
| Control plane interoperability | Stabilize versioning, integrity, telemetry, origin-preserving MCP composition, and caller-owned authorization boundaries. Protocol conformance and tested host compatibility are release gates. |

---

## Explicit Non-Goals

Stating these prevents recurring proposals and scope creep.

- **Executing skill scripts.** The SDK retrieves scripts; it does not run them. Sandboxed
  execution is the host application's responsibility. We will document the hazard, not own it.
- **Authoring or hosting UI.** That belongs to a control plane built on top of the SDK, not to the
  SDK itself.
- **Owning an identity system.** Providers accept caller-supplied credentials and remote MCP
   deployments integrate with standard authorization. Building an identity provider, approval UI,
   or enterprise authorization service is outside the SDK.
- **Being an agent framework.** Frameworks connect through MCP. The SDK does not own their
   orchestration, conversation state, tool permissions, or execution sandbox.
- **Maintaining native framework adapters.** The LangChain and Microsoft Agent Framework
   integrations were removed in v0.7. New framework support uses MCP examples.
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
