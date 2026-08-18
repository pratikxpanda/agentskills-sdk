"""Microsoft Agent Framework integration for Agent Skills.

This package bridges :mod:`agentskills_core` and `Microsoft Agent Framework
<https://github.com/microsoft/agent-framework>`_, providing:

* :class:`AgentSkillsContextProvider` -- a
  :class:`agent_framework.ContextProvider` that automatically
  injects skill awareness into an agent's session context.
* :func:`get_tools` -- generates eight
  :class:`~agent_framework.FunctionTool` instances that let an
  AI agent consume skills.
* :func:`get_tools_usage_instructions` -- returns agent-facing
  instructions explaining how to use the tools.
* :data:`METADATA_LOADED_SKILLS` -- the ``context.metadata`` key under
  which the provider publishes the skills loaded so far this session,
  for other context providers to read.

Install::

    pip install agentskills-agentframework
"""

from agentskills_agentframework.context_provider import AgentSkillsContextProvider
from agentskills_agentframework.session import METADATA_LOADED_SKILLS
from agentskills_agentframework.tools import get_tools, get_tools_usage_instructions

__all__ = [
    "METADATA_LOADED_SKILLS",
    "AgentSkillsContextProvider",
    "get_tools",
    "get_tools_usage_instructions",
]
