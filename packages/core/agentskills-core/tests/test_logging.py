"""Tests for the shared logging namespace and URL redaction."""

import logging

import pytest

from agentskills_core import LOGGER_NAMESPACE, REDACTED, get_logger, redact_url


class TestGetLogger:
    def test_namespace_root(self):
        assert LOGGER_NAMESPACE == "agentskills"

    @pytest.mark.parametrize(
        ("module", "expected"),
        [
            ("agentskills_core.validation", "agentskills.core.validation"),
            ("agentskills_core.registry", "agentskills.core.registry"),
            ("agentskills_fs.local", "agentskills.fs.local"),
            ("agentskills_http.static", "agentskills.http.static"),
            ("agentskills_mcp_server.config", "agentskills.mcp_server.config"),
        ],
    )
    def test_rewrites_distribution_prefix(self, module, expected):
        assert get_logger(module).name == expected

    def test_every_logger_descends_from_the_namespace_root(self):
        """One setLevel on the root must reach the whole SDK."""
        root = logging.getLogger(LOGGER_NAMESPACE)
        child = get_logger("agentskills_http.static")
        assert child.name.startswith(f"{root.name}.")

    def test_null_handler_attached_to_root(self):
        root = logging.getLogger(LOGGER_NAMESPACE)
        assert any(isinstance(h, logging.NullHandler) for h in root.handlers)

    def test_library_attaches_no_output_handler(self):
        """A library must never decide where its records go."""
        root = logging.getLogger(LOGGER_NAMESPACE)
        assert all(isinstance(h, logging.NullHandler) for h in root.handlers)


class TestRedactUrl:
    def test_drops_query_string(self):
        out = redact_url("https://cdn.example.com/skills/a/SKILL.md?sig=SECRET&se=2030")
        assert "SECRET" not in out
        assert out == f"https://cdn.example.com/skills/a/SKILL.md?{REDACTED}"

    def test_drops_fragment(self):
        out = redact_url("https://cdn.example.com/a#token=SECRET")
        assert "SECRET" not in out

    def test_drops_userinfo(self):
        out = redact_url("https://user:hunter2@cdn.example.com/a/SKILL.md")
        assert "hunter2" not in out
        assert "user" not in out
        assert out == "https://cdn.example.com/a/SKILL.md"

    def test_keeps_port(self):
        assert redact_url("http://localhost:8080/a") == "http://localhost:8080/a"

    def test_relative_to_drops_scheme_and_host(self):
        out = redact_url(
            "https://cdn.example.com/skills/a/SKILL.md?sig=SECRET",
            relative_to="https://cdn.example.com/skills",
        )
        assert out == "/a/SKILL.md"

    def test_relative_to_tolerates_trailing_slash(self):
        out = redact_url(
            "https://cdn.example.com/skills/a/SKILL.md",
            relative_to="https://cdn.example.com/skills/",
        )
        assert out == "/a/SKILL.md"

    def test_relative_to_falls_back_without_leaking_query(self):
        """An empty relative path must not fall back to the raw URL."""
        out = redact_url(
            "https://cdn.example.com/skills?sig=SECRET",
            relative_to="https://cdn.example.com/skills",
        )
        assert "SECRET" not in out

    def test_non_matching_base_still_drops_host(self):
        out = redact_url(
            "https://other.example.com/a/SKILL.md?sig=SECRET",
            relative_to="https://cdn.example.com",
        )
        assert "SECRET" not in out
        assert "other.example.com" not in out

    def test_empty_url(self):
        assert redact_url("") == REDACTED
