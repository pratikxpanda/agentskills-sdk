"""Tests for report rendering and exit codes."""

from __future__ import annotations

import io
import json
from pathlib import Path

from agentskills_cli.findings import ERROR, WARNING, Finding, SkillReport
from agentskills_cli.render import count, exit_code, render_github, render_json, render_text


def _report(*findings: Finding) -> SkillReport:
    return SkillReport("alpha", Path("skills/alpha"), list(findings))


ERROR_FINDING = Finding(ERROR, "spec", "body is empty", line=7)
WARNING_FINDING = Finding(WARNING, "missing-version", "no version field")
OTHER_FILE_FINDING = Finding(
    ERROR, "eval-no-cases", "needs cases", file="skills/alpha/evals/cases.yaml"
)


class TestCount:
    def test_totals_across_reports(self):
        assert count([_report(ERROR_FINDING), _report(WARNING_FINDING, WARNING_FINDING)]) == (1, 2)


class TestExitCode:
    def test_clean_run_passes(self):
        assert exit_code([_report()]) == 0

    def test_errors_always_fail(self):
        assert exit_code([_report(ERROR_FINDING)]) == 1

    def test_warnings_pass_by_default(self):
        assert exit_code([_report(WARNING_FINDING)]) == 0

    def test_warnings_fail_under_strict(self):
        assert exit_code([_report(WARNING_FINDING)], strict=True) == 1


class TestRenderText:
    def test_clean_skill_is_marked_ok(self):
        out = io.StringIO()

        render_text([_report()], out)

        assert "  ok" in out.getvalue()
        assert "1 skill checked, 0 errors, 0 warnings" in out.getvalue()

    def test_findings_carry_severity_code_and_line(self):
        out = io.StringIO()

        render_text([_report(ERROR_FINDING, WARNING_FINDING)], out)

        text = out.getvalue()
        assert "error   spec (line 7): body is empty" in text
        assert "warning missing-version: no version field" in text
        assert "1 skill checked, 1 error, 1 warning" in text

    def test_a_finding_about_another_file_names_it(self):
        out = io.StringIO()

        render_text([_report(OTHER_FILE_FINDING)], out)

        assert "eval-no-cases (skills/alpha/evals/cases.yaml): needs cases" in out.getvalue()


class TestRenderJson:
    def test_schema(self):
        out = io.StringIO()

        render_json("validate", [_report(ERROR_FINDING)], out)

        payload = json.loads(out.getvalue())
        assert payload == {
            "schemaVersion": 1,
            "command": "validate",
            "ok": False,
            "summary": {"skills": 1, "errors": 1, "warnings": 0},
            "skills": [
                {
                    "id": "alpha",
                    "path": "skills/alpha",
                    "ok": False,
                    "findings": [
                        {
                            "severity": "error",
                            "code": "spec",
                            "message": "body is empty",
                            "line": 7,
                            "file": "skills/alpha/SKILL.md",
                        }
                    ],
                }
            ],
        }

    def test_ok_mirrors_the_exit_code_under_strict(self):
        out = io.StringIO()

        render_json("lint", [_report(WARNING_FINDING)], out, strict=True)

        payload = json.loads(out.getvalue())
        # The skill itself has no errors, but the run failed.
        assert payload["ok"] is False
        assert payload["skills"][0]["ok"] is True


class TestRenderGithub:
    def test_annotations_point_at_the_skill_file(self):
        out = io.StringIO()

        render_github([_report(ERROR_FINDING, WARNING_FINDING)], out)

        lines = out.getvalue().splitlines()
        assert lines[0] == ("::error file=skills/alpha/SKILL.md,line=7,title=spec::body is empty")
        assert lines[1] == (
            "::warning file=skills/alpha/SKILL.md,title=missing-version::no version field"
        )

    def test_summary_line_is_always_written(self):
        out = io.StringIO()

        render_github([_report()], out)

        assert out.getvalue() == "1 skill checked, 0 errors, 0 warnings\n"

    def test_message_and_property_escapes(self):
        out = io.StringIO()
        finding = Finding(ERROR, "spec", "100% wrong:\nline two, really")

        render_github([_report(finding)], out)

        # Only the message is escaped for newlines; the comma and colon
        # matter in properties, where they are the separators.
        assert out.getvalue().splitlines()[0] == (
            "::error file=skills/alpha/SKILL.md,title=spec::100%25 wrong:%0Aline two, really"
        )

    def test_property_separators_are_escaped(self):
        out = io.StringIO()
        report = SkillReport("alpha", Path("a,b/c:d"), [Finding(ERROR, "spec", "boom")])

        render_github([report], out)

        assert "file=a%2Cb/c%3Ad/SKILL.md" in out.getvalue()

    def test_a_finding_about_another_file_annotates_that_file(self):
        out = io.StringIO()

        render_github([_report(OTHER_FILE_FINDING)], out)

        assert "file=skills/alpha/evals/cases.yaml,title=eval-no-cases::" in out.getvalue()
