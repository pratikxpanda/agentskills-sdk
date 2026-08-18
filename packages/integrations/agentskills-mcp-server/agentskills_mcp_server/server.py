"""MCP server builder for Agent Skills.

This module creates a `FastMCP <https://pypi.org/project/mcp/>`_ server
that exposes a :class:`~agentskills_core.SkillRegistry` as a set of MCP
tools and resources.

Tools
-----
Tools give the LLM agent access to skill content:

==============================  =============================================
Tool name                       Description
==============================  =============================================
``get_skill_metadata``          Read frontmatter (name, description, ...).
``get_skill_body``              Load full skill instructions.
``get_skill_reference``         Read a single reference document.
``get_skill_script``            Read a single script.
``get_skill_asset``             Read a single asset.
==============================  =============================================

Resources
---------
Resources provide context for the system prompt:

==========================================  ==============================================
URI                                         Description
==========================================  ==============================================
``skills://catalog/xml``                    XML catalog of all registered skills.
``skills://catalog/markdown``               Markdown catalog of all registered skills.
``skills://tools-usage-instructions``       Workflow instructions for using the tools.
==========================================  ==============================================

The developer reads these resources and injects them into the system
prompt, giving the LLM agent both *what* skills exist and *how* to
interact with them.

Example::

    from agentskills_mcp_server import create_mcp_server

    server = create_mcp_server(registry, name="My Agent")
    server.run()  # stdio by default
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent

from agentskills_core import (
    DEFAULT_MAX_INLINE_BINARY_BYTES,
    DEFAULT_MAX_INLINE_IMAGE_BYTES,
    FAST_PATH_RESOURCE_INSTRUCTIONS,
    FastPath,
    ResourceListingNotSupportedError,
    SkillProvider,
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
) -> str | ImageContent:
    """Return *data* as something the model can actually use.

    A renderable image becomes native :class:`~mcp.types.ImageContent`.
    Everything else -- text, unrecognised binaries, images past the
    ceiling -- falls through to the JSON envelope, which stays exactly
    as it was.
    """
    if vision:
        media = classify_resource(name, data, max_inline_image_bytes=max_inline_image_bytes)
        if media.renderable:
            return ImageContent(
                type="image",
                data=base64.b64encode(data).decode("ascii"),
                mimeType=media.media_type,
            )
    return encode_resource_content(name, data, max_inline_binary_bytes=max_inline_binary_bytes)


# ------------------------------------------------------------------
# Provider resolution
# ------------------------------------------------------------------

#: Provider types that are recognized by :func:`_resolve_provider`.
SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"fs", "http"})


def _resolve_provider(provider_type: str, options: dict[str, Any]) -> SkillProvider:
    """Map a provider type string and options to a concrete provider.

    Args:
        provider_type: One of the :data:`SUPPORTED_PROVIDERS` keys.
        options: Keyword arguments forwarded to the provider
            constructor.  Unknown keys are silently ignored for
            safety (e.g. a ``client`` key cannot be serialized
            to JSON and must not be passed).

    Returns:
        A ready-to-use :class:`~agentskills_core.SkillProvider`.

    Raises:
        ImportError: If the required provider package is not installed.
        ValueError: If *provider_type* is not recognized.
    """
    if provider_type == "fs":
        try:
            from agentskills_fs import LocalFileSystemSkillProvider
        except ImportError as exc:
            raise ImportError(
                "Provider 'fs' requires the agentskills-fs package. "
                "Install it with:  pip install agentskills-fs"
            ) from exc
        root = Path(options.get("root", "."))
        return LocalFileSystemSkillProvider(root=root)

    if provider_type == "http":
        try:
            from agentskills_http import HTTPStaticFileSkillProvider
        except ImportError as exc:
            raise ImportError(
                "Provider 'http' requires the agentskills-http package. "
                "Install it with:  pip install agentskills-http"
            ) from exc
        # Only pass constructor-safe keys; runtime objects like
        # ``client`` cannot be serialized to a config file.
        safe_http_keys = {"base_url", "headers", "params", "resource_manifest"}
        filtered = {k: v for k, v in options.items() if k in safe_http_keys}
        return HTTPStaticFileSkillProvider(**filtered)

    raise ValueError(
        f"Unknown provider type: {provider_type!r}. "
        f"Supported types: {', '.join(sorted(SUPPORTED_PROVIDERS))}"
    )


# ------------------------------------------------------------------
# Server builder
# ------------------------------------------------------------------


def create_mcp_server(
    registry: SkillRegistry,
    *,
    name: str,
    instructions: str | None = None,
    max_inline_binary_bytes: int = DEFAULT_MAX_INLINE_BINARY_BYTES,
    fast_path: FastPath | None = None,
    vision: bool = False,
    max_inline_image_bytes: int = DEFAULT_MAX_INLINE_IMAGE_BYTES,
) -> FastMCP:
    """Build an MCP server that exposes an Agent Skills registry.

    The returned :class:`~mcp.server.fastmcp.FastMCP` server is
    transport-agnostic.  Call ``server.run()`` to start with the
    default stdio transport, or ``server.run(transport="streamable-http")``
    for HTTP.

    **Tools** let the LLM agent read skill content (metadata,
    body, references, scripts, assets).  **Resources** provide
    the skill catalog and usage instructions for system-prompt
    injection.

    Args:
        registry: The :class:`~agentskills_core.SkillRegistry` whose
            skills should be exposed via MCP.
        name: Display name for the MCP server.  Clients see this
            during the MCP initialization handshake.  Required.
        instructions: Optional server-level instructions sent to the
            MCP client during initialization.  Use this to describe
            the server's purpose or capabilities.
        max_inline_binary_bytes: Size ceiling for inlining binary
            resources as base64.  Larger resources are described but
            not returned.  See
            :func:`~agentskills_core.encode_resource_content`.
        fast_path: A :class:`~agentskills_core.FastPath` from
            :func:`~agentskills_core.resolve_fast_path`.  When given,
            both catalog resources serve the skill's body directly, the
            usage-instructions resource drops the selection workflow it
            no longer describes, and the four body-access tools are not
            registered at all.  Resource tools remain.
        vision: When ``True``, bundled images small enough to inline are
            returned as native ``ImageContent`` instead of a base64 JSON
            envelope.  Off by default: handing an image to a text-only
            model is an API error, not a degraded answer, so the caller
            declares the capability rather than the library guessing it.
        max_inline_image_bytes: Size ceiling for native images.  Only
            consulted when ``vision`` is ``True``.  Larger images fall
            back to the JSON envelope.

    Returns:
        A configured :class:`~mcp.server.fastmcp.FastMCP` server
        instance, ready for ``server.run()``.
    """
    mcp = FastMCP(name, instructions=instructions)

    def _tool(func):
        """Register *func* unless the fast path has made it redundant.

        MCP has no way to hide a registered tool later, so the four
        body-access tools are simply never registered rather than
        registered and then declined at call time.
        """
        if fast_path is not None and not fast_path.keeps(func.__name__):
            return func
        return mcp.tool()(func)

    async def _list_resources_json(skill_id: str) -> str:
        """Serialize a skill's resource listing, or why it is unavailable."""
        skill = registry.get_skill(skill_id)
        try:
            return json.dumps(await skill.list_resources())
        except ResourceListingNotSupportedError as exc:
            return json.dumps({"supported": False, "note": str(exc)})

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @_tool
    async def get_skill_metadata(skill_id: str) -> str:
        """Get structured metadata (name, description, and optional fields like license, compatibility, metadata) for a specific skill."""  # noqa: E501
        skill = registry.get_skill(skill_id)
        return json.dumps(await skill.get_metadata())

    @_tool
    async def get_skill_body(skill_id: str) -> str:
        """Get the full instructions and guidance (markdown body) for a specific skill."""
        skill = registry.get_skill(skill_id)
        return await skill.get_body()

    @_tool
    async def get_skill_outline(skill_id: str) -> str:
        """List the sections of a skill's body with an addressable key and an estimated token cost for each, plus the cost of the whole body.

        Use this before get_skill_section when a skill is large and only
        part of it is relevant.  The outline says when fetching the
        whole body is cheaper; believe it.
        """  # noqa: E501
        outline = await registry.get_skill_outline(skill_id)
        return outline.render()

    @_tool
    async def get_skill_section(skill_id: str, key: str) -> str:
        """Get one section of a skill's body, addressed by a key from get_skill_outline.

        Sections do not nest, so a parent section does not include the
        subsections listed under it.
        """
        return await registry.get_skill_section(skill_id, key)

    @_tool
    async def list_skill_resources(skill_id: str) -> str:
        """List the references, scripts, and assets a skill bundles.

        Returns a JSON object keyed by resource kind.  Some skill
        backends cannot enumerate resources; those return
        ``{"supported": false}``, in which case take the resource names
        from the skill body instead.
        """
        return await _list_resources_json(skill_id)

    @_tool
    async def get_skill_reference(skill_id: str, name: str) -> str | ImageContent:
        """Get the full content of a specific reference document from a skill.

        Provide both skill_id and the reference name.  Binary content is
        returned as a JSON envelope with base64 data.
        """
        skill = registry.get_skill(skill_id)
        return _deliver(
            name,
            await skill.get_reference(name),
            vision=vision,
            max_inline_binary_bytes=max_inline_binary_bytes,
            max_inline_image_bytes=max_inline_image_bytes,
        )

    @_tool
    async def get_skill_asset(skill_id: str, name: str) -> str | ImageContent:
        """Get the content of a specific asset from a skill.

        Provide both skill_id and the asset name.  Binary content is
        returned as a JSON envelope with base64 data.
        """
        skill = registry.get_skill(skill_id)
        return _deliver(
            name,
            await skill.get_asset(name),
            vision=vision,
            max_inline_binary_bytes=max_inline_binary_bytes,
            max_inline_image_bytes=max_inline_image_bytes,
        )

    @_tool
    async def get_skill_script(skill_id: str, name: str) -> str:
        """Get the content of a specific script from a skill.

        Provide both skill_id and the script name.  Binary content is
        returned as a JSON envelope with base64 data.
        """
        skill = registry.get_skill(skill_id)
        return encode_resource_content(
            name,
            await skill.get_script(name),
            max_inline_binary_bytes=max_inline_binary_bytes,
        )

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    @mcp.resource("skills://catalog/xml")
    async def skills_catalog_xml() -> str:
        """XML catalog of all registered skills for system-prompt injection."""
        if fast_path is not None:
            return fast_path.prompt
        return await registry.get_skills_catalog(format="xml")

    @mcp.resource("skills://catalog/markdown")
    async def skills_catalog_markdown() -> str:
        """Markdown catalog of all registered skills for system-prompt injection."""
        if fast_path is not None:
            return fast_path.prompt
        return await registry.get_skills_catalog(format="markdown")

    @mcp.resource("skills://{skill_id}/resources")
    async def skill_resources(skill_id: str) -> str:
        """Resource listing for a single skill, grouped by kind."""
        return await _list_resources_json(skill_id)

    @mcp.resource("skills://tools-usage-instructions")
    def skills_tools_usage_instructions() -> str:
        """Workflow instructions explaining how to use the Agent Skills tools."""
        if fast_path is not None:
            return FAST_PATH_RESOURCE_INSTRUCTIONS
        return _TOOLS_USAGE_INSTRUCTIONS

    return mcp


_TOOLS_USAGE_INSTRUCTIONS = """\
## How to Use Agent Skills

You have access to a set of **Agent Skills** — curated knowledge \
bundles that contain step-by-step instructions, reference documents, \
scripts, and assets. The available skills are listed in the catalog.

### Workflow

1. **Pick a skill** — Choose the most relevant skill from the catalog \
based on the user's request.
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
