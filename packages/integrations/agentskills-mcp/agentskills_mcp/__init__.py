"""MCP server integration for Agent Skills.

This package bridges :mod:`agentskills_core` and the `Model Context
Protocol <https://modelcontextprotocol.io>`_, providing:

* :func:`create_mcp_server` -- builds a :class:`~mcp.server.fastmcp.FastMCP`
  server that exposes skills as MCP tools and resources.

Quick start::

    from agentskills_core import SkillRegistry
    from agentskills_mcp import create_mcp_server

    registry = SkillRegistry()
    # ... register skills ...

    server = create_mcp_server(registry, name="My Agent")
    server.run()  # stdio by default

Install::

    pip install agentskills-modelcontextprotocol
"""

from agentskills_mcp.server import create_mcp_server

__all__ = ["create_mcp_server"]
