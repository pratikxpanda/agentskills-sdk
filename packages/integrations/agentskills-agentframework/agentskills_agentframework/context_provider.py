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
* Attaches eight typed ``FunctionTool`` instances (the same set
  produced by ``get_tools()``) so the agent can drill into individual
  skills on demand.

The provider is **session-aware**. Agent Framework gives it a ``state``
dict that survives across ``agent.run()`` calls, and it uses that for
two things: caching the assembled prompt so a multi-turn session does
not re-read the registry every turn, and remembering which skill bodies
the agent already pulled so their catalog entries can be replaced by a
one-line reminder. The second is what actually makes turn N+1 cheaper —
caching saves provider I/O, not tokens.

Because the registry accepts any
:class:`~agentskills_core.SkillProvider` back-end — filesystem, HTTP,
or custom — a single ``AgentSkillsContextProvider`` can aggregate
skills from multiple sources.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Literal

from agent_framework import ContextProvider, FunctionTool

from agentskills_core import FastPath, SkillRegistry, get_logger

from .session import (
    METADATA_LOADED_SKILLS,
    already_injected,
    body_loads_in,
    cached_prompt,
    loaded_skills,
    mark_injected,
    record_loaded,
    store_prompt,
)
from .tools import get_tools, get_tools_usage_instructions

if TYPE_CHECKING:
    from agent_framework import AgentSession, SessionContext, SupportsAgentRun

_logger = get_logger(__name__)


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

_ALREADY_LOADED_NOTE = (
    "Already loaded, full instructions earlier in this conversation: {skill_ids}."
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


class AgentSkillsContextProvider(ContextProvider):
    """Expose a :class:`~agentskills_core.SkillRegistry` to an Agent Framework agent.

    Wraps a registry of any-backend skills and hooks into the agent
    lifecycle to supply three things at the start of every run:

    * **Skills catalog** — a compact listing of registered skill
      names and descriptions, appended to the session prompt.
    * **Typed tool set** — eight ``FunctionTool`` instances that let the
      agent fetch metadata, full instructions, outlines, sections,
      references, scripts, and assets individually.
    * **Tools usage instructions** — guidance on the progressive-disclosure
      workflow so the agent knows how and when to invoke each tool.

    Across a multi-turn session it also:

    * Caches the assembled prompt in ``state``, keyed by the registry's
      skill set and the skills already loaded, so an unchanged session
      does no registry I/O after the first turn.
    * Records in ``state["loaded_skills"]`` every skill whose full body
      the agent fetched, and prunes those entries from the catalog on
      later turns — their instructions are already in the conversation,
      so advertising them again is paid for twice.
    * Publishes the loaded set on ``context.metadata`` under
      ``"agentskills_loaded_skills"`` so other context providers can
      see what has been put in front of the model.

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
        cache_prompt: Reuse the assembled prompt across runs within a
            session instead of rebuilding it from the registry every
            turn. Pass ``False`` to rebuild each time.
        prune_loaded_skills: Drop the catalog entry of any skill whose
            full body the agent has already fetched this session,
            replacing it with a one-line reminder. Pass ``False`` to
            advertise the whole catalog on every turn.
        fast_path: A :class:`~agentskills_core.FastPath` from
            :func:`~agentskills_core.resolve_fast_path`. When given, the
            skill's body is injected directly and the catalog, the usage
            instructions and the four body-access tools are dropped —
            there is nothing to choose between, so there is no reason to
            spend a model turn choosing. Resource tools remain. Resolve
            it again if the registry changes.
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
        cache_prompt: bool = True,
        prune_loaded_skills: bool = True,
        fast_path: FastPath | None = None,
        source_id: str | None = None,
    ) -> None:
        super().__init__(source_id or self.DEFAULT_SOURCE_ID)
        self._registry = registry
        self._skills_catalog_format = skills_catalog_format
        self._cache_prompt = cache_prompt
        self._prune_loaded_skills = prune_loaded_skills
        self._fast_path = fast_path
        self._tools: list[FunctionTool] = get_tools(registry, fast_path=fast_path)
        self._tools_usage_instructions = get_tools_usage_instructions()

        if skills_instruction_prompt is not None:
            _validate_prompt_template(skills_instruction_prompt)
        self._skills_prompt_template = (
            skills_instruction_prompt or _DEFAULT_SKILLS_INSTRUCTION_PROMPT
        )

    async def _build_prompt(self, registered: list[str], loaded: list[str]) -> str:
        """Assemble the instruction block for one turn."""
        full = self._render(
            await self._registry.get_skills_catalog(format=self._skills_catalog_format)
        )

        # Pruning every skill would leave a catalog saying the agent has
        # no skills, which is a worse lie than repeating entries it has
        # already read.
        prunable = [skill_id for skill_id in loaded if skill_id in registered]
        if not prunable or len(prunable) == len(registered):
            return full

        catalog = await self._registry.get_skills_catalog(
            format=self._skills_catalog_format,
            exclude=prunable,
            total=len(registered),
        )
        note = _ALREADY_LOADED_NOTE.format(skill_ids=", ".join(prunable))
        pruned = self._render(f"{catalog}\n\n{note}")

        # The reminder is a fixed cost and a catalog entry is not, so for
        # very terse skills pruning can cost more than it saves. Declining
        # is quieter than shipping a feature that sometimes makes turn N+1
        # bigger, which is the one thing it exists to prevent.
        if len(pruned) >= len(full):
            _logger.debug(
                "Not pruning %d loaded skill(s): the reminder would cost more than the entries",
                len(prunable),
            )
            return full
        return pruned

    def _render(self, catalog: str) -> str:
        return self._skills_prompt_template.format(
            skills_catalog=catalog,
            tools_usage_instructions=self._tools_usage_instructions,
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

        Calling this twice with the same ``context`` is a no-op the
        second time: the context is marked once contributed to, so a
        pipeline that retries a run cannot double the prompt.

        Args:
            agent: The agent starting this run.
            session: The active session.
            context: Mutable run context to extend.
            state: Provider-scoped mutable state persisted across runs.
        """
        registered = [skill.get_id() for skill in self._registry.list_skills()]
        if not registered:
            return
        if already_injected(context, self.source_id):
            return

        if self._fast_path is not None:
            # The body is in the prompt, so there is nothing to cache
            # against and nothing left to prune.
            context.extend_instructions(self.source_id, self._fast_path.prompt)
            context.extend_tools(self.source_id, self._tools)
            context.metadata[METADATA_LOADED_SKILLS] = [self._fast_path.skill_id]
            mark_injected(context, self.source_id)
            return

        loaded = loaded_skills(state) if self._prune_loaded_skills else []
        signature = repr((self._skills_catalog_format, registered, loaded))

        skills_prompt = cached_prompt(state, signature) if self._cache_prompt else None
        if skills_prompt is None:
            skills_prompt = await self._build_prompt(registered, loaded)
            if self._cache_prompt:
                store_prompt(state, signature, skills_prompt)
        else:
            _logger.debug("Reusing the cached skills prompt for this session")

        context.extend_instructions(self.source_id, skills_prompt)
        context.extend_tools(self.source_id, self._tools)
        context.metadata[METADATA_LOADED_SKILLS] = list(loaded_skills(state))
        mark_injected(context, self.source_id)

    async def after_run(
        self,
        *,
        agent: SupportsAgentRun,
        session: AgentSession,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        """Record which skill bodies the agent pulled during this run.

        Reads the agent's own response rather than wrapping the tools,
        so a caller who passed :func:`~agentskills_agentframework.get_tools`
        output in directly is tracked the same way.

        Args:
            agent: The agent that ran this invocation.
            session: The active session.
            context: The run context, with ``response`` populated.
            state: Provider-scoped mutable state persisted across runs.
        """
        newly_loaded = body_loads_in(context.response)
        if not newly_loaded:
            return

        loaded = record_loaded(state, newly_loaded)
        context.metadata[METADATA_LOADED_SKILLS] = list(loaded)
        _logger.debug("Skills loaded so far this session: %s", ", ".join(loaded))
