"""``agentskills serve`` — run the MCP server over a folder of skills.

The MCP server is an optional extra.  Importing it lazily keeps
``agentskills validate`` — the command CI runs — free of ``mcp`` and
``pydantic``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

from agentskills_core import AgentSkillsError, Skill
from agentskills_core.snapshots import DEFAULT_SNAPSHOT_MAX_BYTES
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_tools.discovery import CliError, SkillLocation


def serve_config(config_path: Path, *, transport: str, check: bool, out: TextIO) -> None:
    """Serve a configuration through the optional MCP integration.

    Args:
        config_path: JSON or YAML server configuration path.
        transport: Requested MCP transport.
        check: Report readiness without starting a listener.
        out: Stream for the readiness report.

    Raises:
        CliError: If MCP support is missing or the configuration cannot be published.
    """
    try:
        from agentskills_mcp_extension.__main__ import run_config
    except ImportError as exc:
        raise CliError(
            "Native serving requires the MCP server extra and MCP SDK 2.2+. "
            "Install 'agentskills-tools[serve]' with 'mcp>=2.2,<3'."
        ) from exc
    try:
        run_config(config_path, transport=transport, check=check, out=out)
    except (AgentSkillsError, OSError, ValueError, TypeError, ImportError) as exc:
        raise CliError(f"cannot publish configured skills: {exc}") from exc


async def build_server(
    root: Path,
    locations: list[SkillLocation],
    *,
    name: str,
    max_file_bytes: int = DEFAULT_SNAPSHOT_MAX_BYTES,
    skill_prompt_shortcuts: bool = False,
) -> Any:
    """Build the real native publication, including catalog-wide consistency checks.

    Raises:
        CliError: If native MCP support is missing or publication fails.
    """
    try:
        from agentskills_mcp_extension import create_mcp_server
    except ImportError as exc:
        raise CliError(
            "Native serving requires the MCP server extra and MCP SDK 2.2+. "
            "Install 'agentskills-tools[serve]' with 'mcp>=2.2,<3'."
        ) from exc
    try:
        provider = LocalFileSystemSkillProvider(root, max_file_bytes=max_file_bytes)
        skills = [Skill(location.skill_id, provider) for location in locations]
        return await create_mcp_server(
            skills, name=name, skill_prompt_shortcuts=skill_prompt_shortcuts
        )
    except (AgentSkillsError, OSError, ValueError) as exc:
        raise CliError(
            f"cannot publish native skills: {exc}\n"
            "Run `agentskills inspect PATH --native` for per-skill diagnostics."
        ) from exc
