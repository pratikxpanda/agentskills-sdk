# ADR 0002 — Optional provider capabilities are opt-in methods with a declared flag

**Status:** Accepted
**Date:** 2026-07
**Packages:** `agentskills-core`, `agentskills-fs`, `agentskills-http`, all integrations

## Context

`SkillProvider` is an ABC whose five methods are all `@abstractmethod`. Every one is
satisfiable by any backend: given a skill ID, return metadata, body, or a named resource.

Two planned features do not fit that shape:

- **`list_resources()`** (v0.3 issue 4) — enumerate the references, scripts and assets a skill
  contains. A filesystem provider can do this trivially. A static HTTP host cannot: there is no
  directory listing over plain HTTP, so enumeration requires an out-of-band manifest that may
  or may not exist.
- **`discover()`** (v0.4 issue 5) — enumerate the skills a backend holds, rather than requiring
  explicit registration. Same asymmetry.

Adding either as a required abstract method breaks every third-party `SkillProvider` at import
time. We are pre-1.0 and can technically do that, but the SDK is published and the contract is
the one thing external implementors depend on. Meanwhile a provider that genuinely cannot
enumerate needs a way to say so that is distinguishable from "enumerated successfully, found
nothing".

That distinction is the crux. An agent told a skill has no references stops looking. An agent
told the provider cannot enumerate goes and reads the skill body for names. Collapsing the two
produces a confidently wrong answer — the same failure mode as the binary-resource corruption
fixed in v0.3 issue 5, where a silent fallback destroyed data without raising.

## Decision

Optional capabilities are **concrete methods on `SkillProvider` with a default implementation
that refuses**, paired with a **declared capability flag**.

```python
class SkillProvider(ABC):
    supports_resource_listing: bool = False

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        raise ResourceListingNotSupportedError(...)
```

Three parts, each load-bearing:

1. **Not abstract.** Existing third-party providers keep working untouched. Adding a capability
   is never a breaking change.
2. **Default raises, never returns empty.** `ResourceListingNotSupportedError` is a new
   `AgentSkillsError` subclass. Returning `{}` would let "cannot enumerate" masquerade as "no
   resources exist". A caller that ignores the flag gets an exception, not a wrong answer.
3. **Flag is a plain attribute, not a `ClassVar`.** Capability can depend on instance
   configuration. `LocalFileSystemSkillProvider` sets it `True` at class level;
   `HTTPStaticFileSkillProvider` sets it per instance from its `resource_manifest` argument,
   because whether a manifest exists is a deployment fact, not a property of the class.

Integrations check the flag and surface the distinction to the agent rather than propagating an
exception, since "this backend cannot list resources" is information the agent can act on, not
an error it can retry.

## Consequences

**Good**

- Third-party providers are unaffected by this and every future capability addition.
- The unsupported case is impossible to confuse with the empty case.
- Providers that can only sometimes enumerate are expressible.
- Callers have a cheap pre-flight check (`if provider.supports_resource_listing:`) that avoids
  exception-driven control flow.

**Costs**

- The contract is weaker. Consumers must branch on capability rather than relying on the
  interface, and static type checking cannot enforce that they do.
- Capability flags and methods can drift apart — a provider could implement `list_resources()`
  and forget the flag, or set the flag and not implement the method. Nothing enforces the pair.
  A conformance test helper in core would close this; deferred until a third capability exists.
- Every new capability adds a flag. Past three or four this wants restructuring into a
  capability set or protocol classes. Revisit at the v1.0 API freeze, which is the natural point
  to promote well-exercised capabilities to required methods in a single documented break.

## Alternatives considered

- **Required abstract method.** Rejected: cleanest contract, but breaks every external
  implementor for a method a third of providers cannot honestly implement. Reconsider at v1.0
  when the shape has stopped moving.
- **Default returning `{}`.** Rejected on the grounds above — it is the option the original
  issue recommended, and it is the one that produces silent wrong answers.
- **Separate mixin ABCs (`SupportsResourceListing`).** Rejected for now: `isinstance` checks are
  cleaner than flags and give better typing, but the mixin cannot express per-instance
  capability, which the HTTP provider needs. Worth revisiting if per-instance capability turns
  out to be rare.
- **Capability negotiation object** (`provider.capabilities` returning a frozen set). Rejected as
  premature for two capabilities; it is the natural refactor once there are several.
