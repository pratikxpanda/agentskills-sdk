"""Pydantic configuration models for Agent Skills MCP servers.

This module defines the declarative configuration schema used by
the CLI (``python -m agentskills_mcp_server --config server.json``).

Example config (JSON)::

    {
        "name": "My Skills Server",
        "skills": [
            {
                "id": "incident-response",
                "provider": "fs",
                "options": {"root": "./skills"}
            }
        ]
    }
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillConfig(BaseModel):
    """Configuration for a single skill."""

    id: str = Field(..., description="Skill identifier")
    provider: str = Field(..., description="Provider type (e.g., 'fs', 'http')")
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific options passed to the provider constructor",
    )


class ServerConfig(BaseModel):
    """Top-level configuration for an Agent Skills MCP server.

    Attributes:
        name: Display name shown to MCP clients during initialization.
        instructions: Optional server-level instructions sent to the
            client during the MCP handshake.
        skills: One or more skill definitions to register.
    """

    name: str = Field(..., description="Display name for the MCP server")
    instructions: str | None = Field(None, description="Optional server-level instructions")
    skills: list[SkillConfig] = Field(..., description="Skills to register", min_length=1)
