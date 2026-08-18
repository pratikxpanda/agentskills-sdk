# Concepts

## Progressive disclosure

Agent Skills are delivered in layers:

1. Catalog entry (name/description) in the system prompt
2. Full skill body only when selected
3. Individual references, scripts, and assets only when needed

This keeps the always-on prompt surface small while preserving depth.

## Selection metadata

`description` carries positive evidence only, so a skill has no way to say where it stops
applying. Two optional frontmatter fields close that gap:

```yaml
---
name: incident-response
description: Triage and mitigate production incidents.
when_to_use:
  - A production service is degraded or down
when_not_to_use:
  - Debugging a failing test locally
---
```

False activation is not a lesser failure than non-activation. It is worse: it costs a full
body load *and* puts instructions written for a different situation in front of the model.

Both fields are optional lists of at most five non-empty strings of at most 200 characters
each. The bounds are not arbitrary — these fields ride in the catalog, so they are charged on
every turn for every registered skill, and a skill needing a sixth condition is usually two
skills. They render next to the description in both catalog formats and are omitted entirely
when absent, so a skill written before they existed renders byte-for-byte as it did.

Callers who want the cheaper catalog back can pass
`get_skills_catalog(selection_hints=False)`.

## Providers

A provider answers five content calls (`get_metadata`, `get_body`, `get_reference`,
`get_script`, `get_asset`) and can optionally support resource listing and skill discovery.

## Registry

`SkillRegistry` coordinates providers and exposes the catalog. `register_all` lets a
provider enumerate and register its own skills atomically.

## Error model

Errors are typed so callers can branch correctly:

- `SkillNotFoundError` for stable absence
- `SkillUnavailableError` for transient/backend failures
- Optional-capability errors for unsupported listing/discovery

## Cost model

The catalog is charged every turn, while skill bodies/resources are charged only when
loaded. The CLI `inspect --cost` reports this split explicitly.
