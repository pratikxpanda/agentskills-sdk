"""Microsoft Agent Framework integration for Agent Skills.

This package bridges :mod:`agentskills_core` and `Microsoft Agent Framework
<https://github.com/microsoft/agent-framework>`_, providing:

* :func:`get_tools` -- generates five
  :class:`~agent_framework.FunctionTool` instances that let an
  AI agent consume skills.
* :func:`get_tools_usage_instructions` -- returns agent-facing
  instructions explaining how to use the tools.
* :class:`AgentSkillsContextProvider` -- an
  :class:`~agent_framework.BaseContextProvider` that automatically injects the
  skills catalog and tool usage instructions into the agent context each turn.

Install::

    pip install agentskills-agentframework
"""

from agentskills_agentframework.context_provider import AgentSkillsContextProvider
from agentskills_agentframework.tools import get_tools, get_tools_usage_instructions

__all__ = [
    "AgentSkillsContextProvider",
    "get_tools",
    "get_tools_usage_instructions",
]
