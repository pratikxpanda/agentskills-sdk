"""Tests for config-driven MCP server creation."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agentskills_core import SkillProvider, SkillRegistry
from agentskills_mcp_server.config import ServerConfig, SkillConfig
from agentskills_mcp_server.server import (
    SUPPORTED_PROVIDERS,
    _resolve_provider,
    create_mcp_server,
)

# ------------------------------------------------------------------
# SkillConfig model
# ------------------------------------------------------------------


class TestSkillConfig:
    def test_minimal(self):
        cfg = SkillConfig(id="my-skill", provider="fs")
        assert cfg.id == "my-skill"
        assert cfg.provider == "fs"
        assert cfg.options == {}

    def test_with_options(self):
        cfg = SkillConfig(
            id="my-skill",
            provider="fs",
            options={"root": "/path/to/skills"},
        )
        assert cfg.options["root"] == "/path/to/skills"

    def test_missing_id_raises(self):
        with pytest.raises(ValidationError):
            SkillConfig(provider="fs")  # type: ignore[call-arg]

    def test_missing_provider_raises(self):
        with pytest.raises(ValidationError):
            SkillConfig(id="my-skill")  # type: ignore[call-arg]

    def test_from_dict(self):
        data = {
            "id": "test",
            "provider": "http",
            "options": {"base_url": "https://example.com"},
        }
        cfg = SkillConfig(**data)
        assert cfg.id == "test"
        assert cfg.provider == "http"
        assert cfg.options["base_url"] == "https://example.com"

    def test_options_default_empty(self):
        cfg = SkillConfig(id="x", provider="fs")
        assert cfg.options == {}


# ------------------------------------------------------------------
# ServerConfig model
# ------------------------------------------------------------------


class TestServerConfig:
    def test_minimal(self):
        cfg = ServerConfig(
            name="Test",
            skills=[SkillConfig(id="s1", provider="fs")],
        )
        assert cfg.name == "Test"
        assert cfg.instructions is None
        assert len(cfg.skills) == 1

    def test_with_instructions(self):
        cfg = ServerConfig(
            name="Test",
            instructions="Custom instructions",
            skills=[SkillConfig(id="s1", provider="fs")],
        )
        assert cfg.instructions == "Custom instructions"

    def test_empty_skills_raises(self):
        with pytest.raises(ValidationError):
            ServerConfig(name="Test", skills=[])

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            ServerConfig(skills=[SkillConfig(id="s1", provider="fs")])  # type: ignore[call-arg]

    def test_multiple_skills(self):
        cfg = ServerConfig(
            name="Multi",
            skills=[
                SkillConfig(id="s1", provider="fs"),
                SkillConfig(
                    id="s2",
                    provider="http",
                    options={"base_url": "https://example.com"},
                ),
            ],
        )
        assert len(cfg.skills) == 2
        assert cfg.skills[0].id == "s1"
        assert cfg.skills[1].id == "s2"

    def test_from_json(self):
        raw = json.dumps(
            {
                "name": "Server",
                "skills": [
                    {"id": "s1", "provider": "fs", "options": {"root": "."}},
                ],
            }
        )
        cfg = ServerConfig(**json.loads(raw))
        assert cfg.name == "Server"
        assert cfg.skills[0].id == "s1"
        assert cfg.skills[0].provider == "fs"

    def test_roundtrip_json(self):
        cfg = ServerConfig(
            name="RT",
            instructions="Hello",
            skills=[
                SkillConfig(id="a", provider="fs", options={"root": "/tmp"}),
            ],
        )
        dumped = cfg.model_dump()
        restored = ServerConfig(**dumped)
        assert restored == cfg


# ------------------------------------------------------------------
# Provider resolution
# ------------------------------------------------------------------


class TestResolveProvider:
    def test_supported_providers_constant(self):
        assert "fs" in SUPPORTED_PROVIDERS
        assert "http" in SUPPORTED_PROVIDERS

    def test_fs_provider(self, tmp_path):
        provider = _resolve_provider("fs", {"root": str(tmp_path)})
        assert isinstance(provider, SkillProvider)

    def test_fs_provider_default_root(self, monkeypatch, tmp_path):
        # Default root is "." — ensure it resolves to a valid dir
        monkeypatch.chdir(tmp_path)
        provider = _resolve_provider("fs", {})
        assert isinstance(provider, SkillProvider)

    def test_http_provider(self):
        provider = _resolve_provider("http", {"base_url": "https://example.com"})
        assert isinstance(provider, SkillProvider)

    def test_http_provider_with_headers(self):
        provider = _resolve_provider(
            "http",
            {
                "base_url": "https://example.com",
                "headers": {"Authorization": "Bearer tok"},
            },
        )
        assert isinstance(provider, SkillProvider)

    def test_http_provider_ignores_unknown_options(self):
        # 'client' is a runtime object — the resolver must ignore it
        provider = _resolve_provider(
            "http",
            {"base_url": "https://example.com", "client": "ignored"},
        )
        assert isinstance(provider, SkillProvider)

    def test_http_provider_with_params(self):
        provider = _resolve_provider(
            "http",
            {
                "base_url": "https://example.com",
                "params": {"sv": "2020", "sig": "token"},
            },
        )
        assert isinstance(provider, SkillProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider type"):
            _resolve_provider("gcs", {})

    def test_fs_import_error(self):
        with (
            patch.dict("sys.modules", {"agentskills_fs": None}),
            pytest.raises(ImportError, match="agentskills-fs"),
        ):
            _resolve_provider("fs", {"root": "."})

    def test_http_import_error(self):
        with (
            patch.dict("sys.modules", {"agentskills_http": None}),
            pytest.raises(ImportError, match="agentskills-http"),
        ):
            _resolve_provider("http", {"base_url": "https://x.com"})


# ------------------------------------------------------------------
# Config-driven server creation (integration test)
# ------------------------------------------------------------------


def _write_skill(tmp_path: Path, skill_id: str) -> None:
    """Create a minimal valid skill directory."""
    skill_dir = tmp_path / skill_id
    skill_dir.mkdir(exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: Test skill.\n---\n# {skill_id}\nInstructions."
    )


async def _build_server_from_config(config: ServerConfig):
    """Replicate the CLI flow: resolve providers, register, build."""
    registry = SkillRegistry()
    for skill_cfg in config.skills:
        provider = _resolve_provider(skill_cfg.provider, skill_cfg.options)
        await registry.register(skill_cfg.id, provider)
    return create_mcp_server(registry, name=config.name, instructions=config.instructions)


class TestConfigDrivenServer:
    async def test_creates_fastmcp_instance(self, tmp_path):
        _write_skill(tmp_path, "test-skill")
        config = ServerConfig(
            name="Test Server",
            skills=[
                SkillConfig(
                    id="test-skill",
                    provider="fs",
                    options={"root": str(tmp_path)},
                )
            ],
        )

        from mcp.server.fastmcp import FastMCP

        server = await _build_server_from_config(config)
        assert isinstance(server, FastMCP)

    async def test_server_name(self, tmp_path):
        _write_skill(tmp_path, "test-skill")
        config = ServerConfig(
            name="My Server",
            skills=[
                SkillConfig(
                    id="test-skill",
                    provider="fs",
                    options={"root": str(tmp_path)},
                )
            ],
        )
        server = await _build_server_from_config(config)
        assert server.name == "My Server"

    async def test_server_instructions(self, tmp_path):
        _write_skill(tmp_path, "test-skill")
        config = ServerConfig(
            name="Test",
            instructions="Custom instructions",
            skills=[
                SkillConfig(
                    id="test-skill",
                    provider="fs",
                    options={"root": str(tmp_path)},
                )
            ],
        )
        server = await _build_server_from_config(config)
        assert server.instructions == "Custom instructions"

    async def test_server_has_5_tools(self, tmp_path):
        _write_skill(tmp_path, "test-skill")
        config = ServerConfig(
            name="Test",
            skills=[
                SkillConfig(
                    id="test-skill",
                    provider="fs",
                    options={"root": str(tmp_path)},
                )
            ],
        )
        server = await _build_server_from_config(config)
        tools = await server.list_tools()
        assert len(tools) == 5

    async def test_server_has_3_resources(self, tmp_path):
        _write_skill(tmp_path, "test-skill")
        config = ServerConfig(
            name="Test",
            skills=[
                SkillConfig(
                    id="test-skill",
                    provider="fs",
                    options={"root": str(tmp_path)},
                )
            ],
        )
        server = await _build_server_from_config(config)
        resources = await server.list_resources()
        assert len(resources) == 3

    async def test_multiple_skills(self, tmp_path):
        _write_skill(tmp_path, "skill-a")
        _write_skill(tmp_path, "skill-b")
        config = ServerConfig(
            name="Multi",
            skills=[
                SkillConfig(
                    id="skill-a",
                    provider="fs",
                    options={"root": str(tmp_path)},
                ),
                SkillConfig(
                    id="skill-b",
                    provider="fs",
                    options={"root": str(tmp_path)},
                ),
            ],
        )
        server = await _build_server_from_config(config)

        # Verify both skills are accessible via tools
        result = await server.call_tool("get_skill_metadata", {"skill_id": "skill-a"})
        meta_a = json.loads(result[0][0].text)
        assert meta_a["name"] == "skill-a"

        result = await server.call_tool("get_skill_metadata", {"skill_id": "skill-b"})
        meta_b = json.loads(result[0][0].text)
        assert meta_b["name"] == "skill-b"

    async def test_instructions_default_none(self, tmp_path):
        _write_skill(tmp_path, "test-skill")
        config = ServerConfig(
            name="Test",
            skills=[
                SkillConfig(
                    id="test-skill",
                    provider="fs",
                    options={"root": str(tmp_path)},
                )
            ],
        )
        server = await _build_server_from_config(config)
        assert server.instructions is None
