"""Registry-backed context provider for Agent Framework agents.

Provides :class:`AgentSkillsContextProvider`, which bridges a
:class:`~agentskills_core.SkillRegistry` and the Agent Framework
lifecycle so that skills catalogs and tools are delivered to the agent
automatically on each ``agent.run()`` call.

With the manual :func:`~agentskills_agentframework.get_tools` approach
callers must build the system prompt themselves; the context provider
eliminates that ceremony:

    context_providers=[AgentSkillsContextProvider(registry)]

On every invocation the provider:

* Generates a lightweight skills catalog from the registry and appends
  it to the session instructions.
* Attaches five typed ``FunctionTool`` instances (the same set
  produced by ``get_tools()``) so the agent can drill into individual
  skills on demand.

Because the registry accepts any
:class:`~agentskills_core.SkillProvider` back-end — filesystem, HTTP,
or custom — a single ``AgentSkillsContextProvider`` can aggregate
skills from multiple sources.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Literal

from agent_framework import BaseContextProvider, FunctionTool

from agentskills_core import SkillRegistry

from .tools import get_tools, get_tools_usage_instructions

if TYPE_CHECKING:
    from agent_framework import AgentSession, SessionContext, SupportsAgentRun


_DEFAULT_SKILLS_INSTRUCTION_PROMPT = """\
You have access to a set of skills that provide domain-specific \
knowledge, procedures, and supporting resources. \
Use them when a task aligns with a skill's domain.

{skills_catalog}

{tools_usage_instructions}\
"""


class AgentSkillsContextProvider(BaseContextProvider):
    """Expose a :class:`~agentskills_core.SkillRegistry` to an Agent Framework agent.

    Wraps a registry of any-backend skills and hooks into the agent
    lifecycle to supply three things at the start of every run:

    * **Skills catalog** — a compact listing of registered skill
      names and descriptions, appended to the session prompt.
    * **Typed tool set** — five ``FunctionTool`` instances that let the
      agent fetch metadata, full instructions, references, scripts, and
      assets individually.
    * **Tools usage instructions** — guidance on the progressive-disclosure
      workflow so the agent knows how and when to invoke each tool.

    The tool surface intentionally uses *typed* resource tools
    (``get_skill_reference``, ``get_skill_script``, ``get_skill_asset``)
    rather than a single generic reader so that the agent has clear
    semantic signal about the kind of content it is requesting.

    Args:
        registry: The :class:`~agentskills_core.SkillRegistry` whose
            skills should be exposed.

    Keyword Args:
        skills_instruction_prompt: Custom prompt template. Must contain
            ``{skills_catalog}`` and ``{tools_usage_instructions}`` placeholders.
            When ``None``, a sensible default is used.
        skills_catalog_format: Format for the skills catalog —
            ``"xml"`` (default) or ``"markdown"``.
        source_id: Unique identifier for this provider instance.

    Example::

        from agentskills_agentframework import AgentSkillsContextProvider
        from agentskills_core import SkillRegistry

        registry = SkillRegistry()
        await registry.register("incident-response", provider)

        skills_context_provider = AgentSkillsContextProvider(registry)

        agent = client.as_agent(
            name="SREAssistant",
            instructions="You are an SRE assistant.",
            context_providers=[skills_context_provider],
        )
        response = await agent.run("What severity is a full DB outage?")
    """

    DEFAULT_SOURCE_ID: ClassVar[str] = "agentskills"

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        skills_instruction_prompt: str | None = None,
        skills_catalog_format: Literal["xml", "markdown"] = "xml",
        source_id: str | None = None,
    ) -> None:
        super().__init__(source_id or self.DEFAULT_SOURCE_ID)
        self._registry = registry
        self._skills_catalog_format = skills_catalog_format
        self._tools: list[FunctionTool] = get_tools(registry)
        self._tools_usage_instructions = get_tools_usage_instructions()

        if skills_instruction_prompt is not None:
            # Validate that the custom template has the required placeholders.
            required = {"{skills_catalog}", "{tools_usage_instructions}"}
            # Check presence of required placeholders (before format-escapes).
            for placeholder in required:
                if placeholder not in skills_instruction_prompt:
                    raise ValueError(
                        "skills_instruction_prompt must contain {skills_catalog} and "
                        "{tools_usage_instructions} placeholders. "
                        "Escape literal braces by doubling them ({{ or }})."
                    )
            try:
                skills_instruction_prompt.format(skills_catalog="", tools_usage_instructions="")
            except (KeyError, IndexError, ValueError) as exc:
                raise ValueError(
                    "skills_instruction_prompt must contain {skills_catalog} and "
                    "{tools_usage_instructions} placeholders. "
                    "Escape literal braces by doubling them ({{ or }})."
                ) from exc
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
        """Append skills catalog, tools, and usage instructions to the run context.

        Does nothing when the registry is empty, so agents without any
        registered skills pay no prompt-budget cost.

        Args:
            agent: The agent starting this run.
            session: The active session.
            context: Mutable run context to extend.
            state: Provider-scoped mutable state persisted across runs.
        """
        if not self._registry.list_skills():
            return

        skills_catalog = await self._registry.get_skills_catalog(format=self._skills_catalog_format)
        skills_prompt = self._skills_prompt_template.format(
            skills_catalog=skills_catalog,
            tools_usage_instructions=self._tools_usage_instructions,
        )

        context.extend_instructions(self.source_id, skills_prompt)
        context.extend_tools(self.source_id, self._tools)
