"""End-to-end tests for the ``agentskills`` command."""

from __future__ import annotations

import json
import logging
import runpy
import sys

import pytest

from agentskills_cli.cli import main
from agentskills_core import LOGGER_NAMESPACE


class TestValidate:
    def test_clean_run_exits_zero(self, write_skill, skills_root, capsys):
        write_skill("alpha")

        assert main(["validate", str(skills_root)]) == 0
        assert "1 skill checked, 0 errors" in capsys.readouterr().out

    def test_broken_skill_exits_one(self, write_skill, skills_root, capsys):
        write_skill("alpha", "no frontmatter")

        assert main(["validate", str(skills_root)]) == 1
        assert "frontmatter-missing" in capsys.readouterr().out

    def test_json_format(self, write_skill, skills_root, capsys):
        write_skill("alpha")

        main(["validate", str(skills_root), "--format", "json"])

        payload = json.loads(capsys.readouterr().out)
        assert payload["command"] == "validate"
        assert payload["ok"] is True

    def test_missing_path_exits_two(self, tmp_path, capsys):
        assert main(["validate", str(tmp_path / "nope")]) == 2
        assert "error: not a directory" in capsys.readouterr().err

    def test_github_format_annotates_the_skill_file(self, write_skill, skills_root, capsys):
        write_skill("alpha", "---\nname: alpha\ndescription: oops: yes\n---\n\nBody.")

        assert main(["validate", str(skills_root), "--format", "github"]) == 1

        out = capsys.readouterr().out
        assert out.startswith("::error file=")
        assert "alpha/SKILL.md,line=3,title=frontmatter-invalid-yaml::" in out


class TestLint:
    def test_warnings_do_not_fail_by_default(self, write_skill, skills_root):
        write_skill("alpha", "---\nname: alpha\ndescription: d\n---\n\nBody.")

        assert main(["lint", str(skills_root)]) == 0

    def test_strict_fails_on_warnings(self, write_skill, skills_root):
        write_skill("alpha", "---\nname: alpha\ndescription: d\n---\n\nBody.")

        assert main(["lint", str(skills_root), "--strict"]) == 1

    def test_token_budget_is_configurable(self, write_skill, skills_root, capsys):
        write_skill("alpha")

        main(["lint", str(skills_root), "--max-body-tokens", "1"])

        assert "body-over-token-budget" in capsys.readouterr().out

    def test_json_format(self, write_skill, skills_root, capsys):
        write_skill("alpha")

        main(["lint", str(skills_root), "--format", "json"])

        assert json.loads(capsys.readouterr().out)["command"] == "lint"

    def test_github_format_emits_warning_annotations(self, write_skill, skills_root, capsys):
        write_skill("alpha", "---\nname: alpha\ndescription: d\n---\n\nBody.")

        assert main(["lint", str(skills_root), "--format", "github"]) == 0

        assert "::warning file=" in capsys.readouterr().out


class TestInit:
    def test_scaffolds_and_reports_the_path(self, tmp_path, capsys):
        assert main(["init", "alpha", "--path", str(tmp_path)]) == 0
        assert (tmp_path / "alpha" / "SKILL.md").is_file()
        assert "Created" in capsys.readouterr().out

    def test_bad_name_exits_two(self, tmp_path, capsys):
        assert main(["init", "Bad Name", "--path", str(tmp_path)]) == 2
        assert "error: cannot scaffold" in capsys.readouterr().err


class TestInspect:
    def test_text_output(self, write_skill, skills_root, capsys):
        write_skill("alpha")

        assert main(["inspect", str(skills_root)]) == 0
        assert "catalog entry" in capsys.readouterr().out

    def test_separates_multiple_skills(self, write_skill, skills_root, capsys):
        write_skill("alpha")
        write_skill("beta")

        main(["inspect", str(skills_root)])

        assert "-" * 60 in capsys.readouterr().out

    def test_json_output(self, write_skill, skills_root, capsys):
        write_skill("alpha")

        main(["inspect", str(skills_root), "--format", "json"])

        payload = json.loads(capsys.readouterr().out)
        assert payload["command"] == "inspect"
        assert payload["skills"][0]["id"] == "alpha"


class TestServe:
    def test_runs_the_server_with_the_requested_transport(
        self, write_skill, skills_root, monkeypatch, capsys
    ):
        write_skill("alpha")
        started: dict[str, str] = {}

        class _FakeServer:
            def run(self, transport: str) -> None:
                started["transport"] = transport

        monkeypatch.setattr(
            "agentskills_cli.cli.create_server", lambda registry, name: _FakeServer()
        )

        assert main(["serve", str(skills_root), "--transport", "streamable-http"]) == 0
        assert started == {"transport": "streamable-http"}
        assert "Serving 1 skill " in capsys.readouterr().err

    def test_invalid_skill_exits_two(self, write_skill, skills_root, capsys):
        write_skill("alpha", "---\nname: alpha\n---\n\nbody")

        assert main(["serve", str(skills_root)]) == 2
        assert "cannot serve" in capsys.readouterr().err


class TestVerbose:
    def test_attaches_a_stderr_handler_to_the_sdk_namespace(self, write_skill, skills_root, capsys):
        write_skill("alpha")
        logger = logging.getLogger(LOGGER_NAMESPACE)
        before = list(logger.handlers)

        try:
            main(["validate", str(skills_root), "-v"])
            assert "agentskills.cli" in capsys.readouterr().err
        finally:
            logger.handlers = before
            logger.setLevel(logging.NOTSET)


class TestParser:
    def test_a_command_is_required(self):
        with pytest.raises(SystemExit):
            main([])

    def test_inspect_does_not_offer_the_github_format(self, write_skill, skills_root):
        write_skill("alpha")

        # inspect produces no findings, so it has nothing to annotate.
        with pytest.raises(SystemExit):
            main(["inspect", str(skills_root), "--format", "github"])


class TestModuleEntryPoint:
    def test_python_m_agentskills_cli_exits_with_the_command_status(
        self, write_skill, skills_root, monkeypatch
    ):
        write_skill("alpha", "no frontmatter")
        monkeypatch.setattr(sys, "argv", ["agentskills", "validate", str(skills_root)])

        with pytest.raises(SystemExit) as exit_info:
            runpy.run_module("agentskills_cli", run_name="__main__")

        assert exit_info.value.code == 1
