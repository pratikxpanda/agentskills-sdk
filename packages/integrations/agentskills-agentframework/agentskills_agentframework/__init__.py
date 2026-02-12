"""Microsoft Agent Framework integration for Agent Skills.

This package bridges :mod:`agentskills_core` and `Microsoft Agent Framework
<https://github.com/microsoft/agent-framework>`_, providing:

* :func:`get_tools` -- generates five
  :class:`~agent_framework.FunctionTool` instances that let an
  AI agent consume skills.
* :func:`get_tools_usage_instructions` -- returns agent-facing
  instructions explaining how to use the tools.

Install::

    pip install agentskills-agentframework
"""

from agentskills_agentframework.tools import get_tools, get_tools_usage_instructions

__all__ = [
    "get_tools",
    "get_tools_usage_instructions",
]
