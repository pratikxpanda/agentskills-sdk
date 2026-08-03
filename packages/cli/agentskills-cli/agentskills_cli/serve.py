"""``agentskills serve`` — run the MCP server over a folder of skills.

The MCP server is an optional extra.  Importing it lazily keeps
``agentskills validate`` — the command CI runs — free of ``mcp`` and
``pydantic``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentskills_cli.discovery import CliError, SkillLocation
from agentskills_core import SkillRegistry, get_logger
from agentskills_fs import LocalFileSystemSkillProvider

_logger = get_logger(__name__)


async def build_registry(root: Path, locations: list[SkillLocation]) -> SkillRegistry:
    """Register every discovered skill against one filesystem provider.

    Raises:
        CliError: If a skill fails validation.  Registration is atomic,
            so one bad skill would otherwise fail the whole server with
            a message that does not say which command diagnoses it.
    """
    provider = LocalFileSystemSkillProvider(root)
    registry = SkillRegistry()
    try:
        await registry.register([(location.skill_id, provider) for location in locations])
    except ValueError as exc:
        raise CliError(f"cannot serve: {exc}\nRun `agentskills validate` for details.") from exc
    _logger.info("Registered %d skills from %s", len(locations), root)
    return registry


def create_server(registry: SkillRegistry, *, name: str) -> Any:
    """Build the MCP server, or explain how to install it.

    Raises:
        CliError: If the ``serve`` extra is not installed.
    """
    try:
        from agentskills_mcp_server.server import create_mcp_server
    except ImportError as exc:
        raise CliError(
            "`agentskills serve` needs the MCP server. "
            "Install it with:  pip install 'agentskills-cli[serve]'"
        ) from exc
    return create_mcp_server(registry, name=name)
