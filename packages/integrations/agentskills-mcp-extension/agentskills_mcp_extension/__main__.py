"""Run an Agent Skills MCP server from a config file.

Usage::

    python -m agentskills_mcp_extension --config server.json
    python -m agentskills_mcp_extension --config server.yaml
    python -m agentskills_mcp_extension --config server.json --transport streamable-http

The tools distribution also provides ``agentskills serve --config server.json``.

The config file is a JSON or YAML document conforming to
:class:`~agentskills_mcp_extension.config.ServerConfig`.

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
        "args": ["-m", "agentskills_mcp_extension", "--config", "server.json"]
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
from contextlib import AsyncExitStack
from importlib.metadata import version
from pathlib import Path
from typing import TextIO


def main() -> None:
    """Parse CLI arguments, load config, and start the MCP server."""
    parser = argparse.ArgumentParser(
        prog="python -m agentskills_mcp_extension",
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
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check provider readiness and publication, then print JSON without listening.",
    )
    args = parser.parse_args()

    try:
        run_config(args.config, transport=args.transport, check=args.check, out=sys.stdout)
    except FileNotFoundError:
        print(
            f"Error: config file not found: {args.config}",
            file=sys.stderr,
        )
        sys.exit(1)


def run_config(
    config_path: Path,
    *,
    transport: str = "stdio",
    check: bool = False,
    out: TextIO | None = None,
) -> None:
    """Publish configured skills, closing owned providers before serving.

    Args:
        config_path: JSON or YAML server configuration path.
        transport: Transport used when starting the server.
        check: Report readiness without starting a listener.
        out: Stream for the readiness report, defaulting to stdout.
    """
    raw = config_path.read_text(encoding="utf-8")

    if config_path.suffix in (".yaml", ".yml"):
        import yaml  # type: ignore[import-untyped]

        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError:
            raise ValueError("Invalid YAML server configuration") from None
    else:
        data = json.loads(raw)

    # ------------------------------------------------------------------
    # Resolve ${VAR} environment variable placeholders
    # ------------------------------------------------------------------
    from agentskills_mcp_extension.config import resolve_env_vars

    data = resolve_env_vars(data)

    # ------------------------------------------------------------------
    # Build and run
    # ------------------------------------------------------------------
    from agentskills_core import Skill
    from agentskills_mcp_extension import create_mcp_server
    from agentskills_mcp_extension.config import ServerConfig, _resolve_provider

    config = ServerConfig(**data)

    async def _build() -> object:
        async with AsyncExitStack() as stack:
            handles = []
            for skill_cfg in config.skills:
                provider = _resolve_provider(skill_cfg.provider, skill_cfg.options)
                if close := getattr(provider, "aclose", None):
                    stack.push_async_callback(close)
                handles.append(Skill(skill_cfg.id, provider))
            return await create_mcp_server(
                handles,
                name=config.name,
                instructions=config.instructions,
                skill_paths=config.skill_paths,
                listed_skill_ids=config.listed_skill_ids,
                skill_prompt_shortcuts=config.skill_prompt_shortcuts,
                page_size=config.page_size,
                max_skills=config.max_skills,
                max_total_bytes=config.max_total_bytes,
                publication_policy=config.build_publication_policy(),
            )

    server = asyncio.run(_build())
    if check:
        print(
            json.dumps(
                {
                    "status": "ready",
                    "scope": "localServerConstruction",
                    "mcpSdkVersion": version("mcp"),
                    "skillCount": len(config.skills),
                    "providerTypes": sorted({skill.provider for skill in config.skills}),
                    "requiresProtocol": "2026-07-28",
                    "requiresExtension": "io.modelcontextprotocol/skills",
                    "directoryRead": False,
                    "transportTested": False,
                    "authenticationTested": False,
                    "hostBehaviorTested": False,
                    "clientGuidance": "Requires a host implementing the native Skills extension.",
                },
                indent=2,
            ),
            file=out or sys.stdout,
        )
        return
    server.run(transport=transport)


if __name__ == "__main__":
    main()
