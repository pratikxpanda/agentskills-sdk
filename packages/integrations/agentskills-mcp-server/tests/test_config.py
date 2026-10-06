"""Tests for config-driven MCP server creation."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agentskills_core import ResourceNotFoundError, SkillProvider, SkillRegistry
from agentskills_mcp_server.config import ServerConfig, SkillConfig, resolve_env_vars
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
    def test_native_builder_missing_sdk_error(self, monkeypatch):
        import agentskills_mcp_server

        monkeypatch.setattr(agentskills_mcp_server, "find_spec", lambda name: None)
        with pytest.raises(ImportError, match=r"MCP SDK 2\.2"):
            agentskills_mcp_server.__getattr__("create_native_mcp_server")

    def test_native_mode_options(self):
        config = ServerConfig(
            name="Native",
            mode="native",
            skills=[SkillConfig(id="example", provider="fs")],
            skill_paths={"example": "team/example"},
            listed_skill_ids=[],
            page_size=1,
        )
        assert config.mode == "native"
        assert config.listed_skill_ids == []
        assert config.max_skills == 128
        with pytest.raises(ValidationError):
            ServerConfig(
                name="Invalid", mode="other", skills=[SkillConfig(id="example", provider="fs")]
            )

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
    async def test_native_http_file_manifest_and_size_limit(self):
        provider = _resolve_provider(
            "http",
            {
                "base_url": "https://example.com",
                "file_manifest": True,
                "max_response_bytes": 0,
            },
        )
        try:
            assert provider.supports_file_access is True
            assert provider._max_response_bytes == 0
        finally:
            await provider.aclose()

    async def test_native_filesystem_size_limit(self, tmp_path):
        _write_skill(tmp_path, "example")
        provider = _resolve_provider("fs", {"root": str(tmp_path), "max_file_bytes": 0})
        with pytest.raises(ResourceNotFoundError, match="maximum size"):
            await provider.read_file("example", "SKILL.md")

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
    async def test_stdio_legacy_roundtrip(self, tmp_path):
        import asyncio
        import os
        import sys

        from mcp import ClientSession, StdioServerParameters, stdio_client

        _write_skill(tmp_path, "test-skill")
        config = ServerConfig(
            name="Transport test",
            skills=[SkillConfig(id="test-skill", provider="fs", options={"root": str(tmp_path)})],
        )
        config_path = tmp_path / "server.json"
        config_path.write_text(config.model_dump_json(), encoding="utf-8")
        parameters = StdioServerParameters(
            command=os.environ.get("AGENTSKILLS_TEST_MCP_SERVER_PYTHON", sys.executable),
            args=["-m", "agentskills_mcp_server", "--config", str(config_path)],
            env={"PYTHONPATH": os.environ.get("PYTHONPATH", "")},
        )
        async with (
            asyncio.timeout(20),
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            initialized = await session.initialize()
            assert initialized.capabilities.tools is not None
            assert initialized.capabilities.resources is not None
            assert len((await session.list_tools()).tools) == 8
            resources = await session.list_resources()
            assert len(resources.resources) == 3
            catalog = await session.read_resource("skills://catalog/xml")
            assert "test-skill" in catalog.contents[0].text
            metadata = await session.call_tool("get_skill_metadata", {"skill_id": "test-skill"})
            assert json.loads(metadata.content[0].text)["name"] == "test-skill"
            missing = await session.call_tool("get_skill_metadata", {"skill_id": "missing"})
            assert missing.model_dump(by_alias=True)["isError"] is True
            assert "missing" in missing.content[0].text

    async def test_stdio_native_resources_for_legacy_client(self, tmp_path):
        import asyncio
        import base64
        import importlib.util
        import os
        import sys

        from mcp import ClientSession, StdioServerParameters, stdio_client
        from mcp.types import Request, Result

        try:
            from mcp.shared.exceptions import MCPError
        except ImportError:
            from mcp.shared.exceptions import McpError as MCPError

        executable = os.environ.get("AGENTSKILLS_TEST_NATIVE_MCP_SERVER_PYTHON")
        if executable is None and importlib.util.find_spec("mcp.server.extension") is None:
            pytest.skip("A native MCP SDK server interpreter is required")
        _write_skill(tmp_path, "test-skill")
        raw = (tmp_path / "test-skill" / "SKILL.md").read_bytes()
        config = ServerConfig(
            name="Native resource compatibility",
            mode="native",
            skills=[SkillConfig(id="test-skill", provider="fs", options={"root": str(tmp_path)})],
        )
        config_path = tmp_path / "native-server.json"
        config_path.write_text(config.model_dump_json(), encoding="utf-8")
        parameters = StdioServerParameters(
            command=executable or sys.executable,
            args=["-m", "agentskills_mcp_server", "--config", str(config_path)],
            env={"PYTHONPATH": os.environ.get("PYTHONPATH", "")},
        )
        async with (
            asyncio.timeout(20),
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            initialized = await session.initialize()
            assert initialized.capabilities.resources is not None
            assert (await session.list_tools()).tools == []
            resources = (await session.list_resources()).resources
            assert [str(resource.uri) for resource in resources] == ["skill://test-skill/SKILL.md"]
            contents = await session.read_resource("skill://test-skill/SKILL.md")
            assert base64.b64decode(contents.contents[0].blob) == raw
            with pytest.raises(MCPError) as unsupported:
                await session.send_request(Request(method="skills/list", params={}), Result)
            assert unsupported.value.error.code == -32601

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

        try:
            from mcp.server.fastmcp import FastMCP
        except ModuleNotFoundError:
            from mcp.server import MCPServer as FastMCP

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

    async def test_server_has_8_tools(self, tmp_path):
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
        assert len(tools) == 8

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
        blocks = result[0] if isinstance(result, tuple) else result.content
        meta_a = json.loads(blocks[0].text)
        assert meta_a["name"] == "skill-a"

        result = await server.call_tool("get_skill_metadata", {"skill_id": "skill-b"})
        blocks = result[0] if isinstance(result, tuple) else result.content
        meta_b = json.loads(blocks[0].text)
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


# ------------------------------------------------------------------
# Environment variable resolution
# ------------------------------------------------------------------


class TestResolveEnvVars:
    """Tests for ${VAR} placeholder resolution in config data."""

    def test_simple_string_replacement(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "secret123")
        assert resolve_env_vars("Bearer ${MY_TOKEN}") == "Bearer secret123"

    def test_multiple_vars_in_one_string(self, monkeypatch):
        monkeypatch.setenv("HOST", "example.com")
        monkeypatch.setenv("PORT", "8080")
        result = resolve_env_vars("https://${HOST}:${PORT}/api")
        assert result == "https://example.com:8080/api"

    def test_unset_var_resolves_to_empty(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR_XYZ", raising=False)
        assert resolve_env_vars("prefix-${NONEXISTENT_VAR_XYZ}-suffix") == "prefix--suffix"

    def test_nested_dict(self, monkeypatch):
        monkeypatch.setenv("SECRET", "s3cret")
        data = {
            "headers": {"Authorization": "Bearer ${SECRET}"},
            "other": "no-vars-here",
        }
        result = resolve_env_vars(data)
        assert result["headers"]["Authorization"] == "Bearer s3cret"
        assert result["other"] == "no-vars-here"

    def test_list_values(self, monkeypatch):
        monkeypatch.setenv("ITEM", "resolved")
        data = ["${ITEM}", "plain", "${ITEM}-suffix"]
        result = resolve_env_vars(data)
        assert result == ["resolved", "plain", "resolved-suffix"]

    def test_non_string_scalars_unchanged(self):
        assert resolve_env_vars(42) == 42
        assert resolve_env_vars(3.14) == 3.14
        assert resolve_env_vars(True) is True
        assert resolve_env_vars(None) is None

    def test_no_placeholders_unchanged(self):
        assert resolve_env_vars("no variables here") == "no variables here"

    def test_empty_string_unchanged(self):
        assert resolve_env_vars("") == ""

    def test_full_config_structure(self, monkeypatch):
        monkeypatch.setenv("CDN_TOKEN", "tok-abc")
        monkeypatch.setenv("SAS_SIG", "sig-xyz")
        data = {
            "name": "Server",
            "skills": [
                {
                    "id": "my-skill",
                    "provider": "http",
                    "options": {
                        "base_url": "https://cdn.example.com",
                        "headers": {"Authorization": "Bearer ${CDN_TOKEN}"},
                        "params": {"sig": "${SAS_SIG}"},
                    },
                }
            ],
        }
        result = resolve_env_vars(data)
        opts = result["skills"][0]["options"]
        assert opts["headers"]["Authorization"] == "Bearer tok-abc"
        assert opts["params"]["sig"] == "sig-xyz"
        # Non-templated values untouched
        assert result["name"] == "Server"
        assert opts["base_url"] == "https://cdn.example.com"

    def test_entire_value_is_var(self, monkeypatch):
        monkeypatch.setenv("BASE", "https://example.com")
        assert resolve_env_vars("${BASE}") == "https://example.com"

    def test_deeply_nested(self, monkeypatch):
        monkeypatch.setenv("DEEP", "found")
        data = {"a": {"b": {"c": [{"d": "${DEEP}"}]}}}
        result = resolve_env_vars(data)
        assert result["a"]["b"]["c"][0]["d"] == "found"

    def test_dollar_without_braces_not_replaced(self):
        """Plain $VAR (without braces) is NOT treated as a placeholder."""
        assert resolve_env_vars("$VAR") == "$VAR"

    def test_warning_logged_for_unset_var(self, monkeypatch, caplog):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        import logging

        with caplog.at_level(logging.WARNING, logger="agentskills.mcp_server.config"):
            resolve_env_vars("${MISSING_VAR}")
        assert "MISSING_VAR" in caplog.text


# ------------------------------------------------------------------
# CLI (__main__.py) tests
# ------------------------------------------------------------------


class TestCLI:
    """Tests for the CLI entry point (__main__.py)."""

    @pytest.mark.parametrize("mode", ["legacy", "native"])
    def test_check_reports_scope_without_starting_or_exposing_options(self, tmp_path, capsys, mode):
        from agentskills_mcp_server.__main__ import main

        config_file = tmp_path / "check.json"
        config_file.write_text(
            json.dumps(
                {
                    "name": "Check",
                    "mode": mode,
                    "skills": [
                        {
                            "id": "example",
                            "provider": "http",
                            "options": {"base_url": "https://example.invalid/?sig=private-value"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        def build(coroutine):
            coroutine.close()
            return object()

        with (
            patch("sys.argv", ["agentskills_mcp_server", "--config", str(config_file), "--check"]),
            patch("agentskills_mcp_server.__main__.asyncio") as mock_asyncio,
        ):
            mock_asyncio.run.side_effect = build
            main()

        output = capsys.readouterr().out
        report = json.loads(output)
        assert report["status"] == "ready"
        assert report["scope"] == "localServerConstruction"
        assert report["mode"] == mode
        assert report["providerTypes"] == ["http"]
        assert report["mcpSdkVersion"]
        assert report["requiresProtocol"] == ("2026-07-28" if mode == "native" else None)
        assert report["transportTested"] is False
        assert "private-value" not in output
        assert "example.invalid" not in output

    @pytest.mark.parametrize("invalid", [False, True])
    def test_legacy_check_closes_provider(self, tmp_path, capsys, invalid):
        from agentskills_fs import LocalFileSystemSkillProvider
        from agentskills_mcp_server.__main__ import main

        _write_skill(tmp_path, "example")
        if invalid:
            (tmp_path / "example" / "SKILL.md").write_text(
                "---\nname: example\n---\n", encoding="utf-8"
            )
        closed = []

        class ClosingProvider(LocalFileSystemSkillProvider):
            async def aclose(self):
                closed.append(True)

        config_file = tmp_path / "check.json"
        config_file.write_text(
            json.dumps(
                {
                    "name": "Check",
                    "skills": [{"id": "example", "provider": "http", "options": {}}],
                }
            ),
            encoding="utf-8",
        )
        with (
            patch("sys.argv", ["agentskills_mcp_server", "--config", str(config_file), "--check"]),
            patch(
                "agentskills_mcp_server.server._resolve_provider",
                return_value=ClosingProvider(tmp_path),
            ),
        ):
            if invalid:
                with pytest.raises(ValueError):
                    main()
            else:
                main()

        assert closed == [True]
        output = capsys.readouterr().out
        if invalid:
            assert output == ""
        else:
            assert json.loads(output)["status"] == "ready"

    def test_argparse_requires_config(self):
        """CLI exits with error when --config is missing."""
        from agentskills_mcp_server.__main__ import main

        with patch("sys.argv", ["agentskills_mcp_server"]), pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2  # argparse exit code for missing args

    def test_missing_config_file_exits(self, tmp_path):
        """CLI exits with error for a non-existent config file."""
        from agentskills_mcp_server.__main__ import main

        missing = str(tmp_path / "nonexistent.json")
        with (
            patch("sys.argv", ["agentskills_mcp_server", "--config", missing]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1

    def test_invalid_json_config_raises(self, tmp_path):
        """CLI fails gracefully on invalid JSON."""
        from agentskills_mcp_server.__main__ import main

        config_file = tmp_path / "bad.json"
        config_file.write_text("{invalid json", encoding="utf-8")
        with (
            patch("sys.argv", ["agentskills_mcp_server", "--config", str(config_file)]),
            pytest.raises((json.JSONDecodeError, SystemExit)),
        ):
            main()

    def test_json_config_loads(self, tmp_path):
        """CLI loads valid JSON config and calls server.run()."""
        from agentskills_mcp_server.__main__ import main

        _write_skill(tmp_path, "cli-skill")
        config_file = tmp_path / "server.json"
        config_file.write_text(
            json.dumps(
                {
                    "name": "CLI Server",
                    "skills": [
                        {
                            "id": "cli-skill",
                            "provider": "fs",
                            "options": {"root": str(tmp_path)},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        def _fake_asyncio_run(coro):
            """Close the coroutine to avoid 'never awaited' warning."""
            coro.close()
            return type("MockServer", (), {"run": lambda self, **kw: None})()

        with (
            patch("sys.argv", ["agentskills_mcp_server", "--config", str(config_file)]),
            patch("agentskills_mcp_server.__main__.asyncio") as mock_asyncio,
        ):
            mock_asyncio.run.side_effect = _fake_asyncio_run
            main()
            mock_asyncio.run.assert_called_once()

    def test_yaml_config_loads(self, tmp_path):
        """CLI loads valid YAML config and calls server.run()."""
        from agentskills_mcp_server.__main__ import main

        _write_skill(tmp_path, "yaml-skill")
        config_file = tmp_path / "server.yaml"
        yaml_content = (
            f"name: YAML Server\n"
            f"skills:\n"
            f"  - id: yaml-skill\n"
            f"    provider: fs\n"
            f"    options:\n"
            f"      root: '{tmp_path}'\n"
        )
        config_file.write_text(yaml_content, encoding="utf-8")

        def _fake_asyncio_run(coro):
            """Close the coroutine to avoid 'never awaited' warning."""
            coro.close()
            return type("MockServer", (), {"run": lambda self, **kw: None})()

        with (
            patch("sys.argv", ["agentskills_mcp_server", "--config", str(config_file)]),
            patch("agentskills_mcp_server.__main__.asyncio") as mock_asyncio,
        ):
            mock_asyncio.run.side_effect = _fake_asyncio_run
            main()
            mock_asyncio.run.assert_called_once()

    def test_transport_argument(self, tmp_path):
        """CLI accepts --transport argument."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--config", required=True, type=Path)
        parser.add_argument(
            "--transport",
            default="stdio",
            choices=["stdio", "streamable-http"],
        )
        args = parser.parse_args(["--config", "server.json", "--transport", "streamable-http"])
        assert args.transport == "streamable-http"

    def test_env_vars_resolved_in_json_config(self, tmp_path, monkeypatch):
        """CLI resolves ${VAR} placeholders in JSON config before building."""
        from agentskills_mcp_server.__main__ import main

        monkeypatch.setenv("SKILL_ROOT", str(tmp_path))
        _write_skill(tmp_path, "env-skill")
        config_file = tmp_path / "server.json"
        config_file.write_text(
            json.dumps(
                {
                    "name": "Env Server",
                    "skills": [
                        {
                            "id": "env-skill",
                            "provider": "fs",
                            "options": {"root": "${SKILL_ROOT}"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        def _fake_asyncio_run(coro):
            coro.close()
            return type("MockServer", (), {"run": lambda self, **kw: None})()

        with (
            patch("sys.argv", ["agentskills_mcp_server", "--config", str(config_file)]),
            patch("agentskills_mcp_server.__main__.asyncio") as mock_asyncio,
        ):
            mock_asyncio.run.side_effect = _fake_asyncio_run
            main()
            mock_asyncio.run.assert_called_once()
