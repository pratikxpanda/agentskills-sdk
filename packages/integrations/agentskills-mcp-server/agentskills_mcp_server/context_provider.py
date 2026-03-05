"""MCP-backed context provider for Agent Framework agents.

Provides :class:`AgentSkillsMcpContextProvider`, a thin adapter that
bridges an existing MCP session into the Agent Framework
:class:`~agent_framework.BaseContextProvider` lifecycle.  It reads the
skills catalog and usage-instruction resources from the MCP server and
injects them as session instructions on every ``agent.run()`` call.

**Tools are not injected by this adapter.** Agent Framework's MCP tool
classes (:class:`~agent_framework.MCPStdioTool`,
:class:`~agent_framework.MCPStreamableHttpTool`, etc.) already handle
tool registration natively.  An MCP tool instance may also expose
non-skill tools, so this adapter cannot reliably filter them.

Usage::

    from agent_framework import Agent, MCPStdioTool
    from agentskills_mcp_server import AgentSkillsMcpContextProvider

    mcp_skills = MCPStdioTool(
        name="skills",
        command="python",
        args=["-m", "agentskills_mcp_server", "--config", "server.json"],
    )

    async with mcp_skills:
        skills_context = AgentSkillsMcpContextProvider(
            session=mcp_skills.session,
        )
        agent = client.as_agent(
            name="SREAssistant",
            instructions="You are an SRE assistant.",
            tools=mcp_skills,
            context_providers=[skills_context],
        )
        response = await agent.run("What severity is a full DB outage?")

This module requires ``agent-framework`` at runtime.  Install via::

    pip install agentskills-mcp-server[agentframework]
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Literal

try:
    from agent_framework import BaseContextProvider
except ImportError as _exc:
    raise ImportError(
        "AgentSkillsMcpContextProvider requires agent-framework. "
        "Install it with:  pip install agentskills-mcp-server[agentframework]"
    ) from _exc

if TYPE_CHECKING:
    from agent_framework import AgentSession, SessionContext, SupportsAgentRun
    from mcp import ClientSession

#: Resource URIs served by ``agentskills-mcp-server``.
_CATALOG_URI_TEMPLATE = "skills://catalog/{format}"
_INSTRUCTIONS_URI = "skills://tools-usage-instructions"

_DEFAULT_SKILLS_INSTRUCTION_PROMPT = """\
You have access to a set of skills that provide domain-specific \
knowledge, procedures, and supporting resources. \
Use them when a task aligns with a skill's domain.

{skills_catalog}

{tools_usage_instructions}\
"""

_PROMPT_VALIDATION_ERROR = (
    "skills_instruction_prompt must contain {skills_catalog} and "
    "{tools_usage_instructions} placeholders. "
    "Escape literal braces by doubling them ({{ or }})."
)


def _validate_prompt_template(template: str) -> None:
    """Validate that *template* contains the required placeholders."""
    for placeholder in ("{skills_catalog}", "{tools_usage_instructions}"):
        if placeholder not in template:
            raise ValueError(_PROMPT_VALIDATION_ERROR)
    try:
        template.format(skills_catalog="", tools_usage_instructions="")
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(_PROMPT_VALIDATION_ERROR) from exc


class AgentSkillsMcpContextProvider(BaseContextProvider):
    """Inject skills catalog and usage instructions from an MCP session.

    This adapter reads two MCP resources on every ``agent.run()`` call
    and appends them to the session context as instructions:

    * ``skills://catalog/xml`` (or ``skills://catalog/markdown``) —
      compact listing of registered skills.
    * ``skills://tools-usage-instructions`` — guidance on the
      progressive-disclosure workflow.

    It does **not** inject tools.  Agent Framework's MCP tool classes
    handle that natively.

    Args:
        session: An MCP :class:`~mcp.ClientSession`, typically
            obtained via ``mcp_tool.session`` from an
            :class:`~agent_framework.MCPStdioTool` or similar.

    Keyword Args:
        skills_instruction_prompt: Custom prompt template.  Must
            contain ``{skills_catalog}`` and
            ``{tools_usage_instructions}`` placeholders.  When
            ``None``, a sensible default is used.
        skills_catalog_format: Format for the skills catalog —
            ``"xml"`` (default) or ``"markdown"``.
        source_id: Unique identifier for this provider instance.

    Example::

        from agent_framework import MCPStdioTool
        from agentskills_mcp_server import AgentSkillsMcpContextProvider

        mcp_skills = MCPStdioTool(name="skills", command="python",
                                  args=["-m", "agentskills_mcp_server",
                                        "--config", "server.json"])
        async with mcp_skills:
            ctx_provider = AgentSkillsMcpContextProvider(
                session=mcp_skills.session,
            )
    """

    DEFAULT_SOURCE_ID: ClassVar[str] = "agentskills_mcp"

    def __init__(
        self,
        session: ClientSession,
        *,
        skills_instruction_prompt: str | None = None,
        skills_catalog_format: Literal["xml", "markdown"] = "xml",
        source_id: str | None = None,
    ) -> None:
        super().__init__(source_id or self.DEFAULT_SOURCE_ID)
        self._session = session
        self._skills_catalog_format = skills_catalog_format

        if skills_instruction_prompt is not None:
            _validate_prompt_template(skills_instruction_prompt)
        self._skills_prompt_template = (
            skills_instruction_prompt or _DEFAULT_SKILLS_INSTRUCTION_PROMPT
        )

    async def before_run(
        self,
        *,
        agent: SupportsAgentRun,
        session: AgentSession,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        """Read MCP resources and inject skills instructions into the run context.

        Reads the skills catalog and tools-usage-instructions resources
        from the MCP session, formats them into the instruction prompt
        template, and calls ``context.extend_instructions()``.

        Args:
            agent: The agent starting this run.
            session: The active Agent Framework session.
            context: Mutable run context to extend.
            state: Provider-scoped mutable state persisted across runs.
        """
        catalog_uri = _CATALOG_URI_TEMPLATE.format(format=self._skills_catalog_format)

        catalog_result = await self._session.read_resource(catalog_uri)
        skills_catalog = catalog_result.contents[0].text

        instructions_result = await self._session.read_resource(_INSTRUCTIONS_URI)
        tools_usage_instructions = instructions_result.contents[0].text

        skills_prompt = self._skills_prompt_template.format(
            skills_catalog=skills_catalog,
            tools_usage_instructions=tools_usage_instructions,
        )

        context.extend_instructions(self.source_id, skills_prompt)
