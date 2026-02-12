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

import json

from langchain_core.tools import StructuredTool

from agentskills_core import SkillRegistry


def get_tools(registry: SkillRegistry) -> list[StructuredTool]:
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

    async def get_skill_reference(skill_id: str, name: str) -> str:
        """Get the content of a specific reference document.

        Binary content is decoded as UTF-8 with replacement characters
        for non-decodable bytes.
        """
        skill = registry.get_skill(skill_id)
        return (await skill.get_reference(name)).decode("utf-8", errors="replace")

    async def get_skill_asset(skill_id: str, name: str) -> str:
        """Get the content of a specific asset.

        Binary content is decoded as UTF-8 with replacement characters
        for non-decodable bytes.
        """
        skill = registry.get_skill(skill_id)
        return (await skill.get_asset(name)).decode("utf-8", errors="replace")

    async def get_skill_script(skill_id: str, name: str) -> str:
        """Get the content of a specific script.

        Binary content is decoded as UTF-8 with replacement characters
        for non-decodable bytes.
        """
        skill = registry.get_skill(skill_id)
        return (await skill.get_script(name)).decode("utf-8", errors="replace")

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
