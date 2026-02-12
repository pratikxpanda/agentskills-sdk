"""LangChain integration for Agent Skills.

This package bridges :mod:`agentskills_core` and `LangChain
<https://python.langchain.com>`_, providing:

* :func:`get_tools` -- generates five
  :class:`~langchain_core.tools.StructuredTool` instances that let an
  LLM agent consume skills.
* :func:`get_tools_usage_instructions` -- returns agent-facing
  instructions explaining how to use the tools.

Install::

    pip install agentskills-langchain
"""

from agentskills_langchain.tools import get_tools, get_tools_usage_instructions

__all__ = [
    "get_tools",
    "get_tools_usage_instructions",
]
