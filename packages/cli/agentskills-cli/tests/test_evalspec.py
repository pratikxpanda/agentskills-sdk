"""Tests for the eval case file format."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentskills_cli.evalspec import (
    Assertion,
    check_skill_evals,
    find_suites,
    load_skill_evals,
    load_suite,
)

MINIMAL = """
skill: demo
cases:
  - prompt: What now?
    expect:
      - contains: rollback
"""


@pytest.fixture
def write_eval(tmp_path: Path):
    """Write an eval file into a skill folder and return its path."""

    def _write(text: str, *, name: str = "cases.yaml", skill: str = "demo") -> Path:
        evals = tmp_path / skill / "evals"
        evals.mkdir(parents=True, exist_ok=True)
        path = evals / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write


def _load(path: Path, skill: str = "demo"):
    return load_suite(path, skill)


class TestFindSuites:
    def test_no_evals_directory_is_not_an_error(self, tmp_path: Path):
        assert find_suites(tmp_path) == []

    def test_finds_yaml_and_yml_sorted(self, write_eval, tmp_path: Path):
        write_eval(MINIMAL, name="b.yaml")
        write_eval(MINIMAL, name="a.yml")

        assert [p.name for p in find_suites(tmp_path / "demo")] == ["a.yml", "b.yaml"]

    def test_ignores_dotfiles_and_other_extensions(self, write_eval, tmp_path: Path):
        write_eval(MINIMAL, name=".hidden.yaml")
        write_eval(MINIMAL, name="notes.md")
        write_eval(MINIMAL, name="real.yaml")

        assert [p.name for p in find_suites(tmp_path / "demo")] == ["real.yaml"]

    def test_ignores_nested_directories(self, write_eval, tmp_path: Path):
        write_eval(MINIMAL)
        (tmp_path / "demo" / "evals" / "sub").mkdir()

        assert [p.name for p in find_suites(tmp_path / "demo")] == ["cases.yaml"]


class TestLoadSuite:
    def test_minimal_suite(self, write_eval):
        suite, findings = _load(write_eval(MINIMAL))

        assert findings == []
        assert suite is not None
        assert suite.skill_id == "demo"
        assert [case.name for case in suite.cases] == ["case-1"]
        assert suite.cases[0].expect == [Assertion("contains", "rollback")]
        assert suite.cases[0].repeat == 1
        assert suite.cases[0].threshold == 1.0
        assert not suite.needs_judge

    def test_the_skill_key_is_optional(self, write_eval):
        suite, findings = _load(
            write_eval("cases:\n  - prompt: hi\n    expect:\n      - regex: h.\n")
        )

        assert findings == []
        assert suite is not None
        assert suite.skill_id == "demo"

    def test_a_mismatched_skill_key_is_an_error(self, write_eval):
        _, [finding] = _load(write_eval(MINIMAL.replace("skill: demo", "skill: other")))

        assert finding.code == "eval-skill-mismatch"
        assert "other" in finding.message

    def test_findings_carry_the_eval_file_not_skill_md(self, write_eval):
        _, [finding] = _load(write_eval(MINIMAL.replace("skill: demo", "skill: other")))

        assert finding.file is not None
        assert finding.file.endswith("cases.yaml")

    def test_unreadable_file(self, tmp_path: Path):
        suite, [finding] = _load(tmp_path / "missing.yaml")

        assert suite is None
        assert finding.code == "eval-unreadable"

    def test_invalid_yaml_reports_a_line(self, write_eval):
        suite, [finding] = _load(write_eval("cases:\n  - prompt: a\n   expect: b\n"))

        assert suite is None
        assert finding.code == "eval-invalid-yaml"
        assert finding.line is not None

    def test_invalid_yaml_without_a_mark(self, write_eval, monkeypatch):
        import yaml

        def explode(_: str) -> None:
            raise yaml.YAMLError("nothing useful")

        monkeypatch.setattr("agentskills_cli.evalspec.yaml.safe_load", explode)
        _, [finding] = _load(write_eval(MINIMAL))

        assert finding.code == "eval-invalid-yaml"
        assert finding.line is None

    def test_empty_file(self, write_eval):
        _, [finding] = _load(write_eval(""))

        assert finding.code == "eval-not-a-mapping"
        assert "nothing" in finding.message

    def test_top_level_sequence(self, write_eval):
        _, [finding] = _load(write_eval("- prompt: a\n"))

        assert finding.code == "eval-not-a-mapping"
        assert "list" in finding.message

    def test_missing_cases(self, write_eval):
        _, [finding] = _load(write_eval("skill: demo\n"))

        assert finding.code == "eval-no-cases"

    def test_empty_cases(self, write_eval):
        _, [finding] = _load(write_eval("skill: demo\ncases: []\n"))

        assert finding.code == "eval-no-cases"

    def test_duplicate_case_names(self, write_eval):
        text = (
            "cases:\n"
            "  - name: same\n    prompt: a\n    expect:\n      - contains: a\n"
            "  - name: same\n    prompt: b\n    expect:\n      - contains: b\n"
        )
        _, [finding] = _load(write_eval(text))

        assert finding.code == "eval-duplicate-case-name"

    def test_invalid_judge_model(self, write_eval):
        _, findings = _load(write_eval(f"judge_model: 3\n{MINIMAL}"))

        assert [f.code for f in findings] == ["eval-invalid-judge-model"]

    def test_a_judge_assertion_needs_a_declared_judge(self, write_eval):
        text = "cases:\n  - prompt: a\n    expect:\n      - judge: is helpful\n"
        _, [finding] = _load(write_eval(text))

        assert finding.code == "eval-judge-model-missing"

    def test_a_declared_judge_satisfies_it(self, write_eval):
        text = (
            "judge_model: gpt-4o\ncases:\n  - prompt: a\n    expect:\n      - judge: is helpful\n"
        )
        suite, findings = _load(write_eval(text))

        assert findings == []
        assert suite is not None
        assert suite.judge_model == "gpt-4o"
        assert suite.needs_judge


class TestCases:
    def test_case_is_not_a_mapping(self, write_eval):
        _, [finding] = _load(write_eval("cases:\n  - just a string\n"))

        assert finding.code == "eval-case-not-a-mapping"
        assert "str" in finding.message

    def test_invalid_case_name(self, write_eval):
        _, [finding] = _load(write_eval("cases:\n  - name: 7\n    prompt: a\n"))

        assert finding.code == "eval-invalid-case-name"

    def test_missing_prompt(self, write_eval):
        _, [finding] = _load(write_eval("cases:\n  - expect:\n      - contains: a\n"))

        assert finding.code == "eval-missing-prompt"

    def test_blank_prompt(self, write_eval):
        _, [finding] = _load(
            write_eval('cases:\n  - prompt: "  "\n    expect:\n      - contains: a\n')
        )

        assert finding.code == "eval-missing-prompt"

    def test_missing_expect(self, write_eval):
        _, [finding] = _load(write_eval("cases:\n  - prompt: a\n"))

        assert finding.code == "eval-no-assertions"

    def test_empty_expect(self, write_eval):
        _, [finding] = _load(write_eval("cases:\n  - prompt: a\n    expect: []\n"))

        assert finding.code == "eval-no-assertions"

    def test_every_problem_in_a_case_is_reported_at_once(self, write_eval):
        _, findings = _load(write_eval("cases:\n  - repeat: 0\n"))

        assert {f.code for f in findings} == {
            "eval-missing-prompt",
            "eval-no-assertions",
            "eval-invalid-repeat",
        }

    @pytest.mark.parametrize("value", ["0", "-1", "1.5", "true", "'two'"])
    def test_invalid_repeat(self, write_eval, value: str):
        text = f"cases:\n  - prompt: a\n    expect:\n      - contains: a\n    repeat: {value}\n"
        _, [finding] = _load(write_eval(text))

        assert finding.code == "eval-invalid-repeat"

    @pytest.mark.parametrize("value", ["0", "-0.5", "1.5"])
    def test_out_of_range_threshold(self, write_eval, value: str):
        text = f"cases:\n  - prompt: a\n    expect:\n      - contains: a\n    threshold: {value}\n"
        _, [finding] = _load(write_eval(text))

        assert finding.code == "eval-invalid-threshold"
        assert "greater than 0" in finding.message

    @pytest.mark.parametrize("value", ["true", "'half'"])
    def test_non_numeric_threshold(self, write_eval, value: str):
        text = f"cases:\n  - prompt: a\n    expect:\n      - contains: a\n    threshold: {value}\n"
        _, [finding] = _load(write_eval(text))

        assert finding.code == "eval-invalid-threshold"
        assert "must be a number" in finding.message

    def test_repeat_and_threshold_are_kept(self, write_eval):
        text = (
            "cases:\n  - prompt: a\n    expect:\n      - contains: a\n"
            "    repeat: 5\n    threshold: 0.6\n"
        )
        suite, findings = _load(write_eval(text))

        assert findings == []
        assert suite is not None
        assert suite.cases[0].repeat == 5
        assert suite.cases[0].threshold == 0.6


class TestAssertions:
    def test_assertion_is_not_a_mapping(self, write_eval):
        _, [finding] = _load(write_eval("cases:\n  - prompt: a\n    expect:\n      - contains\n"))

        assert finding.code == "eval-assertion-not-a-mapping"

    def test_assertion_with_two_keys(self, write_eval):
        text = "cases:\n  - prompt: a\n    expect:\n      - contains: a\n        regex: b\n"
        _, [finding] = _load(write_eval(text))

        assert finding.code == "eval-assertion-not-single-keyed"

    def test_unknown_assertion(self, write_eval):
        text = "cases:\n  - prompt: a\n    expect:\n      - resembles: a\n"
        _, [finding] = _load(write_eval(text))

        assert finding.code == "eval-unknown-assertion"
        assert "not_contains" in finding.message

    @pytest.mark.parametrize("value", ["''", "7", "[]"])
    def test_empty_assertion_value(self, write_eval, value: str):
        text = f"cases:\n  - prompt: a\n    expect:\n      - contains: {value}\n"
        _, [finding] = _load(write_eval(text))

        assert finding.code == "eval-empty-assertion"

    def test_regex_must_compile(self, write_eval):
        text = "cases:\n  - prompt: a\n    expect:\n      - regex: '[unclosed'\n"
        _, [finding] = _load(write_eval(text))

        assert finding.code == "eval-invalid-regex"

    def test_describe_is_one_line(self):
        assert Assertion("contains", "x").describe() == "contains: x"

    def test_only_judge_is_judged(self):
        assert Assertion("judge", "x").judged
        assert not Assertion("regex", "x").judged


class TestSkillLevelHelpers:
    def test_check_reports_across_every_file(self, write_eval, tmp_path: Path):
        write_eval(MINIMAL, name="good.yaml")
        write_eval("cases: []\n", name="bad.yaml")

        findings = check_skill_evals(tmp_path / "demo", "demo")

        assert [f.code for f in findings] == ["eval-no-cases"]

    def test_load_returns_the_good_suites_and_the_bad_findings(self, write_eval, tmp_path: Path):
        write_eval(MINIMAL, name="good.yaml")
        write_eval("cases: []\n", name="bad.yaml")

        suites, findings = load_skill_evals(tmp_path / "demo", "demo")

        assert [suite.path.name for suite in suites] == ["good.yaml"]
        assert [f.code for f in findings] == ["eval-no-cases"]

    def test_a_skill_with_no_evals_produces_nothing(self, tmp_path: Path):
        assert check_skill_evals(tmp_path, "demo") == []
        assert load_skill_evals(tmp_path, "demo") == ([], [])
