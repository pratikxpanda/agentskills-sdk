---
title: Compatibility and API Inventory
description: Maintained API surfaces, tested compatibility boundaries, and unresolved decisions before the v1.0 freeze.
---

## Status

This is the v0.9 development audit of the maintained eleven-package SDK. It records current
exports and documented integration contracts. The maintainer approved the pre-1.0 dependency
and deprecation policy below for v0.9. This does not claim a v1.0 API freeze.

The audit compares package exports, documented submodules, source-based runtime signatures,
provider contracts, CLI parsing, and existing tests. The installed-artifact check verifies that
declared package-root exports resolve in a clean environment. It does not certify third-party
hosts, cloud permissions, or production deployments.

## Installation and Versions

Distributions are independently installable but released in lockstep. Install the same release
family for the maintained SDK packages you use. Core remains independent of providers and MCP.
Provider-specific SDKs, publisher verification, and telemetry retain their optional dependencies.

Current development manifests declare Python `>=3.12,<4.0`. Required CI tests Python 3.12, 3.13,
and 3.14. A permitted interpreter version is not evidence that CI has tested it.

The MCP integration requires SDK `>=2.2,<3` and native Skills protocol `2026-07-28`, using the
`io.modelcontextprotocol/skills` extension. Tests cover the SDK 2.2.0 floor and installed-wheel
preflight has also passed with SDK 2.3.0. The unlocked-dependency job is advisory, not a guarantee
that every future dependency release will work.

Starting with v0.9, sibling requirements use a release floor and the next minor as an exclusive
ceiling. For example, 0.9.0 packages require siblings at `>=0.9.0,<0.10.0`. A 0.9.2 release raises
the floor to 0.9.2 without admitting 0.10.0. Installers must not combine different pre-1.0 minor
families. The same policy applies to optional integration dependencies when their extra is selected.
Patch releases within a minor must preserve that minor's supported contracts. Before this change,
the `<1.0` ceiling admitted unverified mixed-minor combinations.
See [ADR 0004](adr/0004-multi-package-lockstep-versioning.md).

## Deprecation Policy

Effective for new deprecations from v0.9, a supported API must remain available for at least one
released minor with a deprecation notice before removal in a later minor. Deprecating in 0.10
allows removal no earlier than 0.11, never in a 0.10 patch. The notice must identify the replacement,
first deprecated version, earliest removal version, and migration steps.

Python deprecations use caller-attributed `DeprecationWarning` on use and tests that assert the
warning. CLI/config deprecations warn on stderr without corrupting machine-readable stdout or
echoing credentials. Release notes and migration docs must carry the notice as well. Removing a
flag, changing a required fixture contract, narrowing a capability, or changing an exception or
schema meaning is reviewable even if Python signatures do not change.

The separately approved v0.9 removal of `agentskills-mcp` is an explicit transition decision,
not evidence that future removals can skip this window. The policy does not resurrect older
retired packages or retroactively add console aliases. No new deprecations are introduced by this
audit. Future 1.0 stability commitments remain a separate decision.

See [ADR 0012](adr/0012-pre-1-compatibility.md) for the approved rationale and consequences.

## Package Roots

Names listed in each package's `__all__` are intentional exports, including helpers and constants.
An exported name is not made private merely because it looks low-level. Existing names are not
removed by this audit. API pages document their signatures and behavior.

| Distribution | Root namespace | Declared root exports | Additional contract |
| --- | --- | --- | --- |
| `agentskills-core` | `agentskills_core` | 46 | Documented trust, policy, refresh, and telemetry submodules |
| `agentskills-adapters` | `agentskills_adapters` | 4 | Imported skill data and source discovery |
| `agentskills-fs` | `agentskills_fs` | 1 | Provider methods and capabilities |
| `agentskills-git` | `agentskills_git` | 2 | Ref resolution, cache configuration, and provider error |
| `agentskills-http` | `agentskills_http` | 2 | Provider options, network policy, and client ownership |
| `agentskills-azure` | `agentskills_azure` | No root exports | Service classes in `blob` and `files` |
| `agentskills-oci` | `agentskills_oci` | 1 | OCI artifact contract, authentication, and client ownership |
| `agentskills-mcp-extension` | `agentskills_mcp_extension` | 6 | Server result, client references, configuration, and module invocation |
| `agentskills-retrieval` | `agentskills_retrieval` | 20 | Selection and embedding protocols and result objects |
| `agentskills-tools` | `agentskills_tools` | 6 | Console commands, reports, lockfiles, and documented model protocol |
| `agentskills-testing` | `agentskills_testing` | 20 | Conformance fixture contract and pytest plugin |

Counts describe this audited development tree. They are an inventory, not a numerical API
baseline: adding an export does not require keeping the count constant.

### Core

The root exposes `Skill`, `SkillRegistry`, `SkillProvider`, snapshot/file types and capture,
validation/parsing, manifests, section and media helpers, fast-path helpers, shared logging,
exceptions, and their declared constants. Prefer the root import when it supplies the name.

The following documented submodule APIs also belong in compatibility review:

- `agentskills_core.trust`: `TrustPolicy`, `DetachedSignature`, `ContentIdentity`,
  `VerificationError`, `content_revision`, and `signature_payload`
- `agentskills_core.policy`: `ContentDecision`, `ContentRejectedError`, `Publication`, and
  `publish_snapshot`
- `agentskills_core.refresh`: `SnapshotCatalog` and `CatalogGeneration`
- `agentskills_core.telemetry`: `DisclosureEvent`, `emit_event`, and `OpenTelemetryObserver`

`SkillRegistry.register` and `register_all` validate metadata and body content. They are not
metadata-only MCP discovery. `capture_skill` requires complete raw-file access and produces a
bounded immutable snapshot. The root still exposes historical fast-path and encoding helpers
for custom hosts. Native MCP publication does not automatically invoke them or activate skills.

See the [core API](packages/core.md) and [trust contracts](trust-and-operability.md).

### Adapters

The complete root export set is `ImportedSkill`, `adapt_path`, `discover_sources`, and
`render_skill_md`. `adapt_path` returns an `ImportedSkill`, not a bare `Skill`. Its `skill`,
`source`, and `skill_md` fields are part of the documented authoring path. Imported instruction
formats do not create framework lifecycle integrations.

See the [adapter API](packages/adapters.md).

### Providers

Root imports are `LocalFileSystemSkillProvider`, `GitSkillProvider`, `GitSkillProviderError`,
`HTTPStaticFileSkillProvider`, `NetworkPolicyError`, and `OCISkillProvider` from their respective
namespaces. Azure intentionally has no root reexports: import `AzureBlobSkillProvider` from
`agentskills_azure.blob` or `AzureFilesSkillProvider` from `agentskills_azure.files` with the
matching extra installed.

`SkillProvider` requires five async accessors: `get_metadata`, `get_body`, `get_script`,
`get_asset`, and `get_reference`. Optional capabilities are separate contracts:

| Capability | Methods | Unsupported default |
| --- | --- | --- |
| `supports_resource_listing` | `list_resources` | `ResourceListingNotSupportedError` |
| `supports_discovery` | `discover` | `DiscoveryNotSupportedError` |
| `supports_file_access` | `list_files`, `read_file` | `FileAccessNotSupportedError` |

Flags can be instance-dependent. An unsupported capability raises rather than reporting an
empty backend. Files and resources return original `bytes`. Unknown skills and resources,
temporary source unavailability, and content drift remain distinguishable error cases.

Constructor settings, public invalidation methods, limits, and documented client ownership
also require compatibility review. HTTP, Azure, and OCI expose async cleanup. Git currently has
no public `close` or `aclose` method and releases cache leases through its finalizer. Do not
invent a uniform close method merely to make the providers look alike.

Provider guides specify their source-specific prerequisites. A successful local fake-client test
does not certify Azure RBAC, share ACL behavior, registry authentication, or deployed networks.

### MCP Integration

The root export set is `create_mcp_server`, `McpSkillIdentity`, `McpSkillReference`,
`McpSkillsClient`, `McpSkillsClientError`, and `McpSkillsCollection`.

`create_mcp_server` is async. Its documented `NativeSkillsServer` result and methods, including
`refresh`, `health`, `list_resources`, `read_resource`, and `secure_http_app`, are not excluded
from review merely because the class is declared in `native` rather than the package root.
Underlying MCP SDK transport APIs remain subject to the supported upstream SDK range.

`McpSkillsClient` accepts a caller-owned session and an explicit origin. Composition retains
`(origin, URI)`, does not register remote content into a local registry, and does not forward or
rehost servers. Callers own sessions, consent, activation, context, and execution policy.

`ServerConfig`, `SkillConfig`, and `TrustConfig` in `agentskills_mcp_extension.config` define
documented deployment configuration. `resolve_env_vars` is an available configuration helper.
The provider IDs, option meanings, defaults, trust settings, preflight report, and module launch
arguments are reviewable contracts. Private option models and `_resolve_provider` are
implementation details, not plugin extension points.

See the [MCP API](packages/mcp-extension.md) and [migration guide](mcp-migration.md).

### Retrieval

The root exports selector protocols and results (`SkillSelector`, `Selection`, `ScoredSkill`),
`LexicalSelector`, `EmbeddingSelector`, `Embedder`, `EmbeddingCache`, `InMemoryEmbeddingCache`,
`SkillDocument`, corpus/catalog helpers, `cosine`, `load_embedder`, `tokenize`, and declared
selection constants. These are opt-in APIs. Selection is not activation or permission to run a
skill, and the SDK does not promise a host injects catalog metadata on every turn.

See the [retrieval API](packages/retrieval.md).

### Tools

The root exports `main`, `CliError`, `SkillLocation`, `discover`, `Finding`, and `SkillReport`.
`main(argv=None, out=None)` returns an integer result for command dispatch. Parser usage errors
still follow argparse's `SystemExit` behavior. Module and console launchers exit the process.

The documented model extension contract is `agentskills_tools.evals.EvalModel`, including
`model_id` and `complete(*, system, prompt)`, returning `ModelResponse`. Model and embedder
factories configured as `module:factory` are application-owned code. Their documented resolution
and invocation behavior is reviewable even when the factory is not a root export.

`agentskills_tools.cost` deliberately reexports `Section`, `split_sections`, and `PREAMBLE_TITLE`.
`agentskills_tools.lint` reexports `estimate_tokens`. These compatibility imports are retained.
The explicit `agentskills_tools.evals.__all__` also exports result types (`AssertionResult`,
`AttemptResult`, `CaseResult`, `SuiteResult`, `VariantResult`), `CompletionCache`, `EvalRunner`,
`check_deterministic`, `eval_exit_code`, `load_model`, `render_results_text`, `results_payload`,
`run_suites`, `BASELINE_SYSTEM`, and `DEFAULT_CACHE_DIR`, as well as the model protocol and response.
These names belong in review rather than being classified as private by omission.

Other cost helpers and CLI implementation modules are not automatically made stable simply
because they have non-underscore names. This audit removes no existing compatibility imports.

See the [tools API and command guide](packages/tools.md).

### Testing

Root exports include the in-memory provider and skill, construction/render helpers, both
conformance suites, `CONTRACT`, and declared fixture data constants. Installing the distribution
registers `agentskills_testing.fixtures` through the `pytest11` entry point. The documented
`sample_skill`, `skill_provider`, and `skill_registry` fixtures are part of the user-facing test kit.

The conformance `provider` fixture contract is a downstream compatibility surface. Adding an
inherited assertion that needs new fixture data is a breaking change even when no function
signature changes. Separate opt-in suites remain the path for additional backend capabilities.

See the [testing API](packages/testing.md).

## CLI and Data Contracts

Only tools installs the `agentskills` console in v0.9. Its commands are `init`, `validate`, `lint`,
`inspect`, `eval`, `serve`, and `lock`. Folder serving and config serving remain distinct input
modes. The MCP distribution retains `python -m agentskills_mcp_extension` and removes the
`agentskills-mcp` executable without an alias.

Command flags, defaults, exit codes, stdout/stderr routing, JSON fields, and GitHub annotation
output require review. Existing exit distinctions are 0 for success, 1 for findings, and 2 for
an invocation that cannot run. Config and folder preflight reports have different formats.

Do not treat every JSON document as the same schema:

| Surface | Current version boundary |
| --- | --- |
| Authoring/inspection/evaluation JSON reports | `schemaVersion: 1` |
| Git source lockfile | `lockVersion: 1` |
| MCP Skills messages and manifests | Upstream protocol and extension contracts |
| Server configuration | No explicit schema-version field |
| Config preflight JSON and server health | No independent schema-version field |

Never silently repurpose fields or collapse distinct error meanings. Human-readable report
whitespace is not a replacement for a machine-readable schema. An installed export check alone
cannot detect changed signatures, data semantics, or a name deliberately removed from `__all__`.

## Remaining Decisions Before Stability

These are findings to resolve, not approved API changes:

1. The tools-to-MCP `__main__.run_config` call remains an internal integration contract for 0.9.
   Preserve it across the 0.9 patch family and keep the unified CLI regression tests. Direct Python
   calls are not advertised as a stable general-purpose API. Review its final location before 1.0.
2. Decide whether config, preflight, and health need their own schema-version fields before 1.0.
   Adding a required field now would need migration analysis, not a documentation-only change.
3. Keep existing filesystem/HTTP handling of unknown options through 0.9. The new Git/Azure/OCI
   models are strict. Revisit consistency before 1.0 with migration review, not a silent tightening.
4. Classify helper exports, returned-object methods, and documented submodule APIs explicitly
   before freezing signatures. Nothing already documented is removed by omission from this page.
5. Record supported client and deployment evidence separately. Local SDK tests cannot close the
   production authorization, TLS, or third-party host validation gates.

## Release Review

Every intentional incompatible change needs a rationale, affected packages and surfaces, an
upgrade path, regression coverage, and a release-note callout before tagging. For v0.9 the
confirmed breaking changes are the MCP console removal and rejection of mixed-minor sibling
installations. Distribution and Python namespace names remain unchanged. Other decisions above
remain review items before the v1.0 freeze.

See the [0.9 acceptance criteria](issues/v0.9.md) and
[release checklist](DEVELOPMENT.md#release-checklist).
