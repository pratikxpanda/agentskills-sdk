"""Run an Agent Skills MCP server from a config file.

Usage::

    python -m agentskills_mcp_server --config server.json
    python -m agentskills_mcp_server --config server.yaml
    python -m agentskills_mcp_server --config server.json --transport streamable-http

The config file is a JSON or YAML document conforming to
:class:`~agentskills_mcp_server.config.ServerConfig`.

Example ``server.json``::

    {
        "name": "My Skills Server",
        "skills": [
            {
                "id": "incident-response",
                "provider": "fs",
                "options": {"root": "./skills"}
            },
            {
                "id": "cloud-runbooks",
                "provider": "http",
                "options": {
                    "base_url": "https://cdn.example.com/skills",
                    "headers": {"Authorization": "Bearer ${API_TOKEN}"},
                    "params": {"sv": "2020-08-04", "sig": "${SAS_TOKEN}"}
                }
            }
        ]
    }

String values may contain ``${VAR}`` placeholders that are resolved
from environment variables at load time.  This lets you keep secrets
out of the config file.

MCP client integration (stdio transport)::

    {
        "command": "python",
        "args": ["-m", "agentskills_mcp_server", "--config", "server.json"]
    }

MCP client integration (streamable-http transport)::

    {
        "url": "http://127.0.0.1:8000/mcp"
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def main() -> None:
    """Parse CLI arguments, load config, and start the MCP server."""
    parser = argparse.ArgumentParser(
        prog="agentskills_mcp_server",
        description="Start an Agent Skills MCP server from a config file.",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a JSON or YAML configuration file.",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "streamable-http"],
        help="MCP transport type (default: stdio).",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load config file
    # ------------------------------------------------------------------
    config_path: Path = args.config
    if not config_path.exists():
        print(
            f"Error: config file not found: {config_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    raw = config_path.read_text(encoding="utf-8")

    if config_path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            print(
                "Error: YAML config files require pyyaml. Install with:  pip install pyyaml",
                file=sys.stderr,
            )
            sys.exit(1)
        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)

    # ------------------------------------------------------------------
    # Resolve ${VAR} environment variable placeholders
    # ------------------------------------------------------------------
    from agentskills_mcp_server.config import resolve_env_vars

    data = resolve_env_vars(data)

    # ------------------------------------------------------------------
    # Build and run
    # ------------------------------------------------------------------
    from agentskills_core import SkillRegistry
    from agentskills_mcp_server.config import ServerConfig
    from agentskills_mcp_server.server import _resolve_provider, create_mcp_server

    config = ServerConfig(**data)

    async def _build() -> object:
        registry = SkillRegistry()
        for skill_cfg in config.skills:
            provider = _resolve_provider(skill_cfg.provider, skill_cfg.options)
            await registry.register(skill_cfg.id, provider)
        return create_mcp_server(registry, name=config.name, instructions=config.instructions)

    server = asyncio.run(_build())
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
