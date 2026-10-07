"""``agentskills serve`` — run the MCP server over a folder of skills.

The MCP server is an optional extra.  Importing it lazily keeps
``agentskills validate`` — the command CI runs — free of ``mcp`` and
``pydantic``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentskills_core import AgentSkillsError, Skill
from agentskills_core.snapshots import DEFAULT_SNAPSHOT_MAX_BYTES
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_tools.discovery import CliError, SkillLocation


async def build_native_server(
    root: Path,
    locations: list[SkillLocation],
    *,
    name: str,
    max_file_bytes: int = DEFAULT_SNAPSHOT_MAX_BYTES,
) -> Any:
    """Build the real native publication, including catalog-wide consistency checks.

    Raises:
        CliError: If native MCP support is missing or publication fails.
    """
    try:
        from agentskills_mcp_server import create_native_mcp_server
    except ImportError as exc:
        raise CliError(
            "Native serving requires the MCP server extra and MCP SDK 2.2+. "
            "Install 'agentskills-tools[serve]' with 'mcp>=2.2,<3'."
        ) from exc
    try:
        provider = LocalFileSystemSkillProvider(root, max_file_bytes=max_file_bytes)
        skills = [Skill(location.skill_id, provider) for location in locations]
        return await create_native_mcp_server(skills, name=name)
    except (AgentSkillsError, OSError, ValueError) as exc:
        raise CliError(
            f"cannot publish native skills: {exc}\n"
            "Run `agentskills inspect PATH --native` for per-skill diagnostics."
        ) from exc
