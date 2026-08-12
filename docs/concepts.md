# Concepts

## Progressive disclosure

Agent Skills are delivered in layers:

1. Catalog entry (name/description) in the system prompt
2. Full skill body only when selected
3. Individual references, scripts, and assets only when needed

This keeps the always-on prompt surface small while preserving depth.

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
