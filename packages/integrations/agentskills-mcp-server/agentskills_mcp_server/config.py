"""Pydantic configuration models for Agent Skills MCP servers.

This module defines the declarative configuration schema used by
the CLI (``python -m agentskills_mcp_server --config server.json``).

String values may contain ``${VAR}`` placeholders that are resolved
from environment variables at load time.  Unset variables resolve to
an empty string and emit a warning.

Example config (JSON)::

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
                    "headers": {"Authorization": "Bearer ${API_TOKEN}"}
                }
            }
        ]
    }
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from agentskills_core import SkillProvider, get_logger

_logger = get_logger(__name__)

SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"fs", "http"})


def _resolve_provider(provider_type: str, options: dict[str, Any]) -> SkillProvider:
    if provider_type == "fs":
        try:
            from agentskills_fs import LocalFileSystemSkillProvider
        except ImportError as exc:
            raise ImportError(
                "Provider 'fs' requires the agentskills-fs package. "
                "Install it with:  pip install agentskills-fs"
            ) from exc
        root = Path(options.get("root", "."))
        limits = {key: options[key] for key in ("max_file_bytes",) if key in options}
        return LocalFileSystemSkillProvider(root=root, **limits)

    if provider_type == "http":
        try:
            from agentskills_http import HTTPStaticFileSkillProvider
        except ImportError as exc:
            raise ImportError(
                "Provider 'http' requires the agentskills-http package. "
                "Install it with:  pip install agentskills-http"
            ) from exc
        safe_http_keys = {
            "base_url",
            "headers",
            "params",
            "resource_manifest",
            "file_manifest",
            "max_response_bytes",
        }
        filtered = {key: value for key, value in options.items() if key in safe_http_keys}
        return HTTPStaticFileSkillProvider(**filtered)

    raise ValueError(
        f"Unknown provider type: {provider_type!r}. "
        f"Supported types: {', '.join(sorted(SUPPORTED_PROVIDERS))}"
    )


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
    mode: Literal["native"] = "native"
    skill_paths: dict[str, str] = Field(default_factory=dict)
    listed_skill_ids: list[str] | None = None
    page_size: int = Field(100, gt=0)
    max_skills: int = Field(128, gt=0)
    max_total_bytes: int = Field(64 * 1024 * 1024, ge=0)


# ------------------------------------------------------------------
# Environment variable resolution
# ------------------------------------------------------------------

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def resolve_env_vars(data: Any) -> Any:
    """Recursively resolve ``${VAR}`` placeholders in config data.

    Walks dicts, lists, and strings.  Non-string scalars (``int``,
    ``float``, ``bool``, ``None``) are returned as-is.

    Unset environment variables resolve to an empty string and a
    warning is logged.

    Args:
        data: Parsed config data (typically the dict returned by
            ``json.loads`` or ``yaml.safe_load``).

    Returns:
        A new data structure with all ``${VAR}`` placeholders
        replaced by their environment variable values.
    """
    if isinstance(data, str):
        return _resolve_env_vars_in_string(data)
    if isinstance(data, dict):
        return {k: resolve_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_env_vars(item) for item in data]
    return data


def _resolve_env_vars_in_string(value: str) -> str:
    """Replace ``${VAR_NAME}`` tokens in *value* with ``os.environ``."""

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name, "")
        if not env_value:
            _logger.warning(
                "Environment variable '%s' is not set or empty",
                var_name,
            )
        return env_value

    return _ENV_VAR_RE.sub(_replace, value)
