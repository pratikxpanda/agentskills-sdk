# ADR 0009 — Images are returned natively, behind an opt-in flag

**Status:** Accepted
**Date:** 2026-10
**Packages:** `agentskills-core`, `agentskills-langchain`, `agentskills-agentframework`, `agentskills-mcp-server`

## Context

[ADR 0007](0007-binary-resource-json-envelope.md) made every binary resource a
JSON envelope carrying base64. That gave one shape across three integrations,
and it worked, but it hands a model a picture of a diagram as a wall of base64
that it cannot see. Every modern chat API accepts image content natively;
sending one through a text field is strictly worse for both cost and accuracy.

Fixing this changes what a tool returns, from `str` to a union, in all three
integrations. That is the kind of change that breaks callers quietly, and the
three integrations do not even agree on what "native" means — MCP has
`ImageContent`, LangChain has standard content blocks, Agent Framework has
`Content(type="data")`.

There is also no way to ask a model whether it can see. Handing an image block
to a text-only deployment is an API error from the provider, not a worse
answer, so guessing wrong fails the whole call.

## Decision

**Classification lives in core, once.** `classify_resource()` returns a
`ResourceMedia` saying what the bytes are and whether they are worth rendering.
All three integrations call it and differ only in how they wrap the result.

**Detection is by magic bytes, then by name.** A name is a claim; bytes are
evidence. A `.png` holding a ZIP is not renderable, and a real PNG called
`.dat` is.

**Only PNG, JPEG, GIF and WebP qualify.** PDF is read by some models and
rejected by others, and guessing wrong is an API error. SVG is text that
already arrives readable — rasterising it would replace something the model can
reason about with something it can only look at.

**Native delivery is opt-in, per integration, via `vision=False`.** With the
default, behaviour is byte-for-byte what it was, so this is not a breaking
change and needs no version gate. The caller declares the capability because
only the caller knows which model the tools are bound to.

**Images get their own, much larger ceiling.** `max_inline_image_bytes`
defaults to 5 MiB, the lowest per-image limit among the major vision APIs,
against 64 KiB for opaque binaries. The old cap tracks tokens, and base64 in a
text field is billed per byte; a native image is billed by tile count, so the
same 64 KiB would have turned nearly every real screenshot into a stub saying
it was too large.

**Everything else keeps the envelope from ADR 0007, unchanged.** Text,
unrecognised binaries, and images past the ceiling all fall through to
`encode_resource_content()`. Falling back is always safe, which is why the
classifier is allowed to be conservative.

**Scripts are not affected.** `get_skill_script` still returns `str`. A script
is code; there is nothing to render, and widening its return type would buy
nothing.

## Consequences

**Good**

- A diagram bundled with a skill is something the model can actually see.
- One classifier, so the three integrations cannot drift on what an image is.
- Existing callers are untouched until they ask to be.
- ADR 0007's envelope stays the fallback rather than being replaced, so there
  is no migration.

**Costs**

- Two return types to reason about per resource tool, once `vision` is on.
- The caller has to know whether its model can see, and gets an API error if it
  is wrong. This is a real cost, accepted because the alternative is the
  library guessing.
- `list_skill_resources` still advertises names only, so a caller cannot know
  in advance which resources will come back as images.

## Alternatives considered

- **Sniff the model's capabilities.** Rejected: the integrations are handed a
  registry, not a model, and capability strings are not standardised.
- **Always return native, gated on a major version.** Rejected: it forces every
  caller to change on a schedule set by us, to get a feature many do not need.
- **Classify by file extension.** Rejected: the failure mode is promising a
  renderable image and delivering bytes the provider rejects.
- **Advertise renderability from `list_skill_resources`.** Rejected: it would
  mean fetching and classifying every resource's bytes to answer a listing
  call, and classifying by name alone would sometimes lie. It saves one tool
  call and costs a read of everything.
- **Include PDF.** Rejected for now; revisit when support is uniform.

## Decision history

- [v0.5 issue 6: Vision-native assets](../issues/v0.5.md)
- [ADR 0007 — Binary resources use a JSON envelope](0007-binary-resource-json-envelope.md)
