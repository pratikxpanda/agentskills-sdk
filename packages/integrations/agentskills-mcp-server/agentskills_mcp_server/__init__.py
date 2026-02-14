"""MCP server integration for Agent Skills.

This package bridges :mod:`agentskills_core` and the `Model Context
Protocol <https://modelcontextprotocol.io>`_, providing:

* :func:`create_mcp_server` -- builds a FastMCP server from a
  :class:`~agentskills_core.SkillRegistry`.  Useful when you have
  custom providers or need full control over registration.
* CLI entry-point (``python -m agentskills_mcp_server --config server.json``)
  for zero-code server startup.

Quick start (programmatic)::

    from agentskills_core import SkillRegistry
    from agentskills_mcp_server import create_mcp_server

    registry = SkillRegistry()
    await registry.register("incident-response", my_custom_provider)
    server = create_mcp_server(registry, name="My Agent")
    server.run()  # stdio by default

CLI::

    python -m agentskills_mcp_server --config server.json

Install::

    pip install agentskills-mcp-server
"""

from agentskills_mcp_server.server import create_mcp_server

__all__ = [
    "create_mcp_server",
]
