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

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from agentskills_core import SkillProvider, SkillRegistry

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
        safe_http_keys = {"base_url", "headers", "params"}
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

    Returns:
        A configured :class:`~mcp.server.fastmcp.FastMCP` server
        instance, ready for ``server.run()``.
    """
    mcp = FastMCP(name, instructions=instructions)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def get_skill_metadata(skill_id: str) -> str:
        """Get structured metadata (name, description, and optional fields like license, compatibility, metadata) for a specific skill."""  # noqa: E501
        skill = registry.get_skill(skill_id)
        return json.dumps(await skill.get_metadata())

    @mcp.tool()
    async def get_skill_body(skill_id: str) -> str:
        """Get the full instructions and guidance (markdown body) for a specific skill."""
        skill = registry.get_skill(skill_id)
        return await skill.get_body()

    @mcp.tool()
    async def get_skill_reference(skill_id: str, name: str) -> str:
        """Get the full content of a specific reference document from a skill.

        Provide both skill_id and the reference name.  Binary content is
        decoded as UTF-8 with replacement characters for non-decodable bytes.
        """
        skill = registry.get_skill(skill_id)
        return (await skill.get_reference(name)).decode("utf-8", errors="replace")

    @mcp.tool()
    async def get_skill_asset(skill_id: str, name: str) -> str:
        """Get the content of a specific asset from a skill.

        Provide both skill_id and the asset name.  Binary content is
        decoded as UTF-8 with replacement characters for non-decodable bytes.
        """
        skill = registry.get_skill(skill_id)
        return (await skill.get_asset(name)).decode("utf-8", errors="replace")

    @mcp.tool()
    async def get_skill_script(skill_id: str, name: str) -> str:
        """Get the content of a specific script from a skill.

        Provide both skill_id and the script name.  Binary content is
        decoded as UTF-8 with replacement characters for non-decodable bytes.
        """
        skill = registry.get_skill(skill_id)
        return (await skill.get_script(name)).decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    @mcp.resource("skills://catalog/xml")
    async def skills_catalog_xml() -> str:
        """XML catalog of all registered skills for system-prompt injection."""
        return await registry.get_skills_catalog(format="xml")

    @mcp.resource("skills://catalog/markdown")
    async def skills_catalog_markdown() -> str:
        """Markdown catalog of all registered skills for system-prompt injection."""
        return await registry.get_skills_catalog(format="markdown")

    @mcp.resource("skills://tools-usage-instructions")
    def skills_tools_usage_instructions() -> str:
        """Workflow instructions explaining how to use the Agent Skills tools."""
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
full instructions. Follow these instructions carefully.
4. **Fetch resources on demand** — The skill body will reference \
specific resources by name. Use the appropriate tool to retrieve them:
   - `get_skill_reference(skill_id, name)` — reference documents \
(policies, templates, runbooks)
   - `get_skill_script(skill_id, name)` — executable scripts
   - `get_skill_asset(skill_id, name)` — diagrams, data files, or \
other assets

### Important guidelines

- **Do not guess resource names.** Only fetch resources that are \
explicitly mentioned in the skill body.
- **Follow progressive disclosure.** Read the skill body first, then \
fetch only the resources you need for the current step.
- **One skill at a time.** Focus on the most relevant skill for the \
user's request. If multiple skills apply, address them sequentially.\
"""
