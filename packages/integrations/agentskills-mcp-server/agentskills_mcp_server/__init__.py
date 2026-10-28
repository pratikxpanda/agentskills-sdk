"""MCP server integration for Agent Skills.

This package bridges :mod:`agentskills_core` and the `Model Context
Protocol <https://modelcontextprotocol.io>`_ Skills extension, providing:

* :func:`create_mcp_server` -- asynchronously builds a native Skills server from a
  :class:`~agentskills_core.SkillRegistry`.  Useful when you have
  registry or raw skill handles. No tools or catalog resources are served.
* :class:`McpSkillsClient` -- consumes native Skills through a caller-owned MCP
  client session without registering or eagerly reading skill bodies.
* Optional ``skill_prompt_shortcuts`` -- exposes one user-invoked ``use-skill``
  prompt without granting tools or execution permissions.
* CLI entry-point (``python -m agentskills_mcp_server --config server.json``)
  for zero-code server startup.

Quick start (programmatic)::

    from agentskills_core import SkillRegistry
    from agentskills_mcp_server import create_mcp_server

    registry = SkillRegistry()
    await registry.register("incident-response", my_custom_provider)
    server = await create_mcp_server(registry, name="My Agent")
    server.run()  # stdio by default

CLI::

    python -m agentskills_mcp_server --config server.json

Install::

    pip install agentskills-mcp-server
"""

from agentskills_mcp_server.client import (
    McpSkillIdentity,
    McpSkillReference,
    McpSkillsClient,
    McpSkillsClientError,
)
from agentskills_mcp_server.native import create_mcp_server

__all__ = [
    "McpSkillIdentity",
    "McpSkillReference",
    "McpSkillsClient",
    "McpSkillsClientError",
    "create_mcp_server",
]
