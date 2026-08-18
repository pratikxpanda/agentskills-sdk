"""LangChain integration for Agent Skills.

This module converts a :class:`~agentskills_core.SkillRegistry` into a
set of :class:`~langchain_core.tools.StructuredTool` instances that an
LLM agent can invoke to read skill metadata and instructions, and
retrieve bundled resources.

Skill *discovery* is handled separately: the application injects the
skill catalog (via :meth:`SkillRegistry.get_skills_catalog`) into the system
prompt so the agent already knows which skills are available.  The tools
here cover **activation and resource retrieval** only.

==============================  =============================================
Tool name                       Description
==============================  =============================================
``get_skill_metadata``          Read frontmatter (name, description, ...).
``get_skill_body``              Load full skill instructions.
``get_skill_outline``           List the body's sections and their cost.
``get_skill_section``           Load one section of the body.
``list_skill_resources``        List bundled resource names by kind.
``get_skill_reference``         Read a single reference document.
``get_skill_script``            Read a single script.
``get_skill_asset``             Read a single asset.
==============================  =============================================

All tools are ``async`` to match the underlying async provider interface.

Example::

    from agentskills_langchain import get_tools

    tools = get_tools(registry)
    # Pass *tools* to a LangChain agent or tool-calling LLM.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from langchain_core.tools import StructuredTool

from agentskills_core import (
    DEFAULT_MAX_INLINE_BINARY_BYTES,
    DEFAULT_MAX_INLINE_IMAGE_BYTES,
    FastPath,
    ResourceListingNotSupportedError,
    SkillRegistry,
    classify_resource,
    encode_resource_content,
)


def _deliver(
    name: str,
    data: bytes,
    *,
    vision: bool,
    max_inline_binary_bytes: int,
    max_inline_image_bytes: int,
) -> str | list[dict[str, Any]]:
    """Return *data* as something the model can actually use.

    A renderable image becomes a one-element list holding a standard
    LangChain image content block, which lands in the ``ToolMessage``
    as multimodal content.  Everything else -- text, unrecognised
    binaries, images past the ceiling -- falls through to the JSON
    envelope, which stays exactly as it was.
    """
    if vision:
        media = classify_resource(name, data, max_inline_image_bytes=max_inline_image_bytes)
        if media.renderable:
            return [
                {
                    "type": "image",
                    "source_type": "base64",
                    "mime_type": media.media_type,
                    "data": base64.b64encode(data).decode("ascii"),
                }
            ]
    return encode_resource_content(name, data, max_inline_binary_bytes=max_inline_binary_bytes)


def get_tools(
    registry: SkillRegistry,
    *,
    max_inline_binary_bytes: int = DEFAULT_MAX_INLINE_BINARY_BYTES,
    fast_path: FastPath | None = None,
    vision: bool = False,
    max_inline_image_bytes: int = DEFAULT_MAX_INLINE_IMAGE_BYTES,
) -> list[StructuredTool]:
    """Build LangChain tools that expose an Agent Skills registry.

    Each tool wraps a :class:`~agentskills_core.SkillRegistry` or
    :class:`~agentskills_core.Skill` method, serialising the result
    as JSON (for dicts) or plain text (for content bodies).
    Tools are **read-only** -- they retrieve content but never execute
    scripts or modify state.

    Skill discovery is handled via the catalog in the system prompt,
    so no ``list_skills`` tool is included.

    All tools are async coroutines.

    Args:
        registry: The :class:`~agentskills_core.SkillRegistry` whose
            skills should be exposed as tools.
        max_inline_binary_bytes: Size ceiling for inlining binary
            resources as base64.  Larger resources are described but
            not returned.  See
            :func:`~agentskills_core.encode_resource_content`.
        fast_path: A :class:`~agentskills_core.FastPath` from
            :func:`~agentskills_core.resolve_fast_path`.  When given,
            the four body-access tools are omitted, because the body is
            already in the prompt.  Resource tools remain.  Use
            ``fast_path.prompt`` in place of the catalog and
            :func:`get_tools_usage_instructions`.
        vision: When ``True``, bundled images small enough to inline are
            returned as native image content blocks instead of a base64
            JSON envelope.  Off by default: handing an image block to a
            text-only model is an API error, not a degraded answer, so
            the caller declares the capability rather than the library
            guessing it.
        max_inline_image_bytes: Size ceiling for native images.  Only
            consulted when ``vision`` is ``True``.  Larger images fall
            back to the JSON envelope.

    Returns:
        A list of :class:`~langchain_core.tools.StructuredTool`
        instances ready to be passed to a LangChain agent.
    """

    async def get_skill_metadata(skill_id: str) -> str:
        """Get structured metadata for a skill."""
        skill = registry.get_skill(skill_id)
        return json.dumps(await skill.get_metadata())

    async def get_skill_body(skill_id: str) -> str:
        """Get the full instructions / markdown body for a skill."""
        skill = registry.get_skill(skill_id)
        return await skill.get_body()

    async def get_skill_outline(skill_id: str) -> str:
        """List the sections of a skill body without loading it."""
        outline = await registry.get_skill_outline(skill_id)
        return outline.render()

    async def get_skill_section(skill_id: str, key: str) -> str:
        """Get one section of a skill body by its outline key."""
        return await registry.get_skill_section(skill_id, key)

    async def list_skill_resources(skill_id: str) -> str:
        """List the resources a skill bundles, grouped by kind."""
        skill = registry.get_skill(skill_id)
        try:
            return json.dumps(await skill.list_resources())
        except ResourceListingNotSupportedError as exc:
            return json.dumps({"supported": False, "note": str(exc)})

    async def get_skill_reference(skill_id: str, name: str) -> str | list[dict[str, Any]]:
        """Get the content of a specific reference document.

        Binary content is returned as a JSON envelope with base64 data,
        unless it is a renderable image and ``vision`` is on.
        """
        skill = registry.get_skill(skill_id)
        return _deliver(
            name,
            await skill.get_reference(name),
            vision=vision,
            max_inline_binary_bytes=max_inline_binary_bytes,
            max_inline_image_bytes=max_inline_image_bytes,
        )

    async def get_skill_asset(skill_id: str, name: str) -> str | list[dict[str, Any]]:
        """Get the content of a specific asset.

        Binary content is returned as a JSON envelope with base64 data,
        unless it is a renderable image and ``vision`` is on.
        """
        skill = registry.get_skill(skill_id)
        return _deliver(
            name,
            await skill.get_asset(name),
            vision=vision,
            max_inline_binary_bytes=max_inline_binary_bytes,
            max_inline_image_bytes=max_inline_image_bytes,
        )

    async def get_skill_script(skill_id: str, name: str) -> str:
        """Get the content of a specific script.

        Binary content is returned as a JSON envelope with base64 data.
        """
        skill = registry.get_skill(skill_id)
        return encode_resource_content(
            name,
            await skill.get_script(name),
            max_inline_binary_bytes=max_inline_binary_bytes,
        )

    tools = [
        StructuredTool.from_function(
            coroutine=get_skill_metadata,
            name="get_skill_metadata",
            description=(
                "Get structured metadata (name, description, and optional "
                "fields like license, compatibility, metadata) for a specific skill."
            ),
        ),
        StructuredTool.from_function(
            coroutine=get_skill_body,
            name="get_skill_body",
            description=(
                "Get the full instructions and guidance (markdown body) for a specific skill."
            ),
        ),
        StructuredTool.from_function(
            coroutine=get_skill_outline,
            name="get_skill_outline",
            description=(
                "List the sections of a skill's body with an addressable key and "
                "an estimated token cost for each, plus the cost of the whole "
                "body. Use this before get_skill_section when a skill is large "
                "and only part of it is relevant. The outline says when fetching "
                "the whole body is cheaper; believe it."
            ),
        ),
        StructuredTool.from_function(
            coroutine=get_skill_section,
            name="get_skill_section",
            description=(
                "Get one section of a skill's body, addressed by a key from "
                "get_skill_outline. Sections do not nest, so a parent section "
                "does not include the subsections listed under it."
            ),
        ),
        StructuredTool.from_function(
            coroutine=list_skill_resources,
            name="list_skill_resources",
            description=(
                "List the references, scripts, and assets a skill bundles. "
                "Returns a JSON object keyed by resource kind. Some skill "
                "backends cannot enumerate resources; those return "
                '{"supported": false} and the resource names must be taken '
                "from the skill body instead."
            ),
        ),
        StructuredTool.from_function(
            coroutine=get_skill_reference,
            name="get_skill_reference",
            description=(
                "Get the full content of a specific reference document "
                "from a skill. Provide both skill_id and the reference name."
            ),
        ),
        StructuredTool.from_function(
            coroutine=get_skill_asset,
            name="get_skill_asset",
            description=(
                "Get the content of a specific asset from a skill. "
                "Provide both skill_id and the asset name."
            ),
        ),
        StructuredTool.from_function(
            coroutine=get_skill_script,
            name="get_skill_script",
            description=(
                "Get the content of a specific script from a skill. "
                "Provide both skill_id and the script name."
            ),
        ),
    ]

    if fast_path is not None:
        tools = [tool for tool in tools if fast_path.keeps(tool.name)]
    return tools


def get_tools_usage_instructions() -> str:
    """Return agent instructions for using the Agent Skills tools.

    This text explains to an LLM agent **how** to use the skill
    tools (``get_skill_metadata``, ``get_skill_body``,
    ``get_skill_reference``, ``get_skill_script``, ``get_skill_asset``)
    following the progressive-disclosure workflow.

    Combine with the skill catalog produced by
    :meth:`SkillRegistry.get_skills_catalog` to give the agent both
    *what* skills are available and *how* to interact with them::

        catalog = await registry.get_skills_catalog(format="xml")
        instructions = get_tools_usage_instructions()
        system_prompt = f"{catalog}\\n\\n{instructions}"

    Returns:
        A multi-line instruction string ready for system-prompt
        insertion.
    """
    return _TOOLS_USAGE_INSTRUCTIONS


_TOOLS_USAGE_INSTRUCTIONS = """\
## How to Use Agent Skills

You have access to a set of **Agent Skills** — curated knowledge \
bundles that contain step-by-step instructions, reference documents, \
scripts, and assets. The available skills are listed above.

### Workflow

1. **Pick a skill** — Choose the most relevant skill from the catalog \
above based on the user's request.
2. **Read metadata** — Call `get_skill_metadata(skill_id)` to get \
structured information (name, description, and optional fields).
3. **Read the body** — Call `get_skill_body(skill_id)` to load the \
full instructions. Follow these instructions carefully. For a large \
skill, call `get_skill_outline(skill_id)` first and then \
`get_skill_section(skill_id, key)` for the parts you need — the \
outline tells you which of the two is cheaper.
4. **Fetch resources on demand** — The skill body will reference \
specific resources by name. Use the appropriate tool to retrieve them:
   - `get_skill_reference(skill_id, name)` — reference documents \
(policies, templates, runbooks)
   - `get_skill_script(skill_id, name)` — executable scripts
   - `get_skill_asset(skill_id, name)` — diagrams, data files, or \
other assets

### Important guidelines

- **Do not guess resource names.** Only fetch resources that are \
explicitly mentioned in the skill body, or that \
`list_skill_resources(skill_id)` reports. That tool returns \
`{"supported": false}` on backends that cannot be enumerated — when \
it does, rely on the skill body alone.
- **Follow progressive disclosure.** Read the skill body first, then \
fetch only the resources you need for the current step.
- **One skill at a time.** Focus on the most relevant skill for the \
user's request. If multiple skills apply, address them sequentially.\
"""
