"""Pydantic configuration models for Agent Skills MCP servers.

This module defines the declarative configuration schema used by
config-driven serving (``agentskills serve --config server.json``).

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

import base64
import binascii
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentskills_core import SkillProvider, get_logger
from agentskills_core.policy import Publication, publish_snapshot
from agentskills_core.snapshots import SkillSnapshot
from agentskills_core.trust import DetachedSignature, TrustPolicy

_logger = get_logger(__name__)

SUPPORTED_PROVIDERS: frozenset[str] = frozenset(
    {"fs", "http", "git", "azure-blob", "azure-files", "oci"}
)


class _ProviderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)


class _GitOptions(_ProviderOptions):
    repository: str = Field(min_length=1)
    ref: str = Field(min_length=1)
    cache_dir: str = Field(min_length=1)
    subdirectory: str = "."
    max_cache_bytes: int = Field(256 * 1024 * 1024, ge=0)
    max_total_cache_bytes: int = Field(1024 * 1024 * 1024, ge=0)
    refresh: bool = False


class _AzureBlobOptions(_ProviderOptions):
    account_url: str = Field(min_length=1)
    container_name: str = Field(min_length=1)
    prefix: str = ""
    max_file_bytes: int = Field(10 * 1024 * 1024, ge=0)


class _AzureFilesOptions(_ProviderOptions):
    account_url: str = Field(min_length=1)
    share_name: str = Field(min_length=1)
    token_intent: Literal["backup"]
    prefix: str = ""
    max_file_bytes: int = Field(10 * 1024 * 1024, ge=0)
    max_files: int = Field(10_000, ge=1)
    max_depth: int = Field(64, ge=0)


class _OCIOptions(_ProviderOptions):
    repository: str = Field(min_length=1)
    insecure: bool = False
    tls_verify: bool | str = True
    auth_backend: str = "token"
    max_files: int = Field(512, ge=1)
    max_file_bytes: int = Field(10 * 1024 * 1024, ge=0)
    max_total_bytes: int = Field(16 * 1024 * 1024, ge=0)


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
            "allow_private_network",
            "require_tls",
            "timeout",
            "max_retries",
            "retry_backoff",
            "max_retry_delay",
            "skill_manifest",
        }
        filtered = {key: value for key, value in options.items() if key in safe_http_keys}
        return HTTPStaticFileSkillProvider(**filtered)

    if provider_type == "git":
        settings = _GitOptions(**options).model_dump(exclude_unset=True)
        settings["cache_dir"] = Path(settings["cache_dir"])
        try:
            from agentskills_git import GitSkillProvider
        except ImportError as exc:
            raise ImportError(
                "Provider 'git' requires agentskills-git. "
                "Install it with: pip install agentskills-git"
            ) from exc
        return GitSkillProvider(**settings)

    if provider_type == "azure-blob":
        settings = _AzureBlobOptions(**options).model_dump(exclude_unset=True)
        try:
            from agentskills_azure.blob import AzureBlobSkillProvider
        except ImportError as exc:
            raise ImportError(
                "Provider 'azure-blob' requires agentskills-azure[blob]. "
                "Install it with: pip install 'agentskills-azure[blob]'"
            ) from exc
        return AzureBlobSkillProvider(**settings)

    if provider_type == "azure-files":
        settings = _AzureFilesOptions(**options).model_dump(exclude_unset=True)
        try:
            from agentskills_azure.files import AzureFilesSkillProvider
        except ImportError as exc:
            raise ImportError(
                "Provider 'azure-files' requires agentskills-azure[files]. "
                "Install it with: pip install 'agentskills-azure[files]'"
            ) from exc
        return AzureFilesSkillProvider(**settings)

    if provider_type == "oci":
        settings = _OCIOptions(**options).model_dump(exclude_unset=True)
        try:
            from agentskills_oci import OCISkillProvider
        except ImportError as exc:
            raise ImportError(
                "Provider 'oci' requires agentskills-oci. "
                "Install it with: pip install agentskills-oci"
            ) from exc
        return OCISkillProvider(**settings)

    raise ValueError(
        f"Unknown provider type: {provider_type!r}. "
        f"Supported types: {', '.join(sorted(SUPPORTED_PROVIDERS))}"
    )


class TrustConfig(BaseModel):
    """Deployment-owned detached Ed25519 proof and base64 public-key allowlist."""

    model_config = ConfigDict(hide_input_in_errors=True)
    origin: str
    trusted_keys: dict[str, str] = Field(default_factory=dict)
    require_signature: bool = True
    revision: str | None = None
    version: str | None = None
    key_id: str | None = None
    signature: str | None = None

    def verify_and_publish(self, snapshot: SkillSnapshot) -> Publication:
        """Decode deployment-owned keys and verify the complete original capture."""
        try:
            keys = {
                name: base64.b64decode(value, validate=True)
                for name, value in self.trusted_keys.items()
            }
            proof = (
                None
                if self.signature is None
                else DetachedSignature(
                    self.key_id or "", base64.b64decode(self.signature, validate=True)
                )
            )
        except (ValueError, binascii.Error):
            raise ValueError("Trust keys and signatures must be valid base64") from None
        return publish_snapshot(
            snapshot,
            trust=TrustPolicy(
                self.origin, keys, self.require_signature, self.revision, self.version
            ),
            proof=proof,
        )


class SkillConfig(BaseModel):
    """Configuration for a single skill."""

    model_config = ConfigDict(hide_input_in_errors=True)
    id: str = Field(..., description="Skill identifier")
    provider: str = Field(
        ..., description="Provider type: fs, http, git, azure-blob, azure-files, or oci"
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific options passed to the provider constructor",
    )
    trust: TrustConfig | None = None


class ServerConfig(BaseModel):
    """Top-level configuration for an Agent Skills MCP server.

    Attributes:
        name: Display name shown to MCP clients during initialization.
        instructions: Optional server-level instructions sent to the
            client during the MCP handshake.
        skills: One or more skill definitions to register.
    """

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")
    name: str = Field(..., description="Display name for the MCP server")
    instructions: str | None = Field(None, description="Optional server-level instructions")
    skills: list[SkillConfig] = Field(..., description="Skills to register", min_length=1)
    skill_paths: dict[str, str] = Field(default_factory=dict)
    listed_skill_ids: list[str] | None = None
    skill_prompt_shortcuts: bool = False
    page_size: int = Field(100, gt=0)
    max_skills: int = Field(128, gt=0)
    max_total_bytes: int = Field(64 * 1024 * 1024, ge=0)

    def build_publication_policy(self) -> Callable[[SkillSnapshot], Publication] | None:
        """Require an explicit trust policy for every skill when verification is configured."""
        configured = {skill.id: skill.trust for skill in self.skills if skill.trust is not None}
        if not configured:
            return None
        if len(configured) != len(self.skills):
            raise ValueError(
                "Configure trust for every skill. Use require_signature=false for unsigned sources."
            )

        def publish(snapshot: SkillSnapshot) -> Publication:
            return configured[snapshot.skill_id].verify_and_publish(snapshot)

        return publish


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
