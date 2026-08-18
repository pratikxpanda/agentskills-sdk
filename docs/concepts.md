# Concepts

## Progressive disclosure

Agent Skills are delivered in layers:

1. Catalog entry (name/description) in the system prompt
2. Body outline — section keys and their token cost — when a skill is large
3. One section, or the full skill body, only when selected
4. Individual references, scripts, and assets only when needed

This keeps the always-on prompt surface small while preserving depth.

## Section-level disclosure

Layer 2 exists because a long skill body is all-or-nothing: an agent that needs the rollback
procedure pays for the onboarding notes too. `get_skill_outline(skill_id)` returns the body's
headings as addressable keys with a token estimate for each, and
`get_skill_section(skill_id, key)` fetches one.

```text
'incident-response': ~439 tokens in 8 sections.

- incident-response (~14) — Incident Response
  - when-to-declare-an-incident (~50) — When to Declare an Incident
  - roles (~70) — Roles
  ...
```

Three properties of that design are load-bearing:

- **Keys are flat slugs, with an ordinal on collision.** Two `## Setup` headings become
  `setup` and `setup-2`. A hierarchical path would imply a tree the splitter does not build.
- **Sections do not nest.** A section covers its own text up to the next heading of *any*
  level, so fetching a parent does not include what is indented under it. The indentation in
  the outline shows depth; it does not show containment. This is what makes the parts sum to
  the whole, which `agentskills inspect --cost` depends on.
- **The outline says when not to use it.** A section fetch costs a tool call, a model turn,
  and the outline that preceded it. Below `WHOLE_BODY_CHEAPER_TOKENS` (1000) the rendered
  outline tells the agent to call `get_skill_body` instead, and past about three sections it
  says the same. Shipping the split without that guidance would make the common case worse in
  order to improve the rare one.

The rendering lives in `SkillOutline.render()` in core rather than in each integration, so the
three integrations cannot drift into quoting different costs for the same skill.

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
