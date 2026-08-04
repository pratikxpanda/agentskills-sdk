"""Tests for the eval runner."""

from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pytest

from agentskills_cli.discovery import CliError
from agentskills_cli.evals import (
    BASELINE_SYSTEM,
    AssertionResult,
    AttemptResult,
    CompletionCache,
    EvalRunner,
    ModelResponse,
    SuiteResult,
    VariantResult,
    check_deterministic,
    eval_exit_code,
    load_model,
    render_results_text,
    results_payload,
    run_suites,
)
from agentskills_cli.evalspec import Assertion, EvalCase, EvalSuite


class ScriptedModel:
    """A model that answers from a script and records what it was asked."""

    def __init__(self, answers: list[str] | None = None, model_id: str = "scripted") -> None:
        self.model_id = model_id
        self._answers = answers or ["with the skill"]
        self.calls: list[tuple[str, str]] = []

    async def complete(self, *, system: str, prompt: str) -> ModelResponse:
        self.calls.append((system, prompt))
        index = min(len(self.calls) - 1, len(self._answers) - 1)
        return ModelResponse(self._answers[index])


class SystemAwareModel:
    """Answers correctly only when the system prompt is not empty."""

    model_id = "system-aware"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *, system: str, prompt: str) -> ModelResponse:
        self.calls += 1
        return ModelResponse("rollback now" if system else "have you tried turning it off")


def _case(*expect: Assertion, name: str = "c", repeat: int = 1, threshold: float = 1.0) -> EvalCase:
    return EvalCase(name, "what now?", list(expect), repeat, threshold)


def _suite(*cases: EvalCase, judge_model: str | None = None) -> EvalSuite:
    return EvalSuite(Path("evals/cases.yaml"), "demo", list(cases), judge_model)


class TestDeterministicAssertions:
    @pytest.mark.parametrize(
        ("kind", "value", "text", "expected"),
        [
            ("contains", "roll", "rollback", True),
            ("contains", "delete", "rollback", False),
            ("not_contains", "delete", "rollback", True),
            ("not_contains", "roll", "rollback", False),
            ("regex", r"roll\w+", "rollback", True),
            ("regex", r"^delete", "rollback", False),
        ],
    )
    async def test_matching(self, kind: str, value: str, text: str, expected: bool):
        assert check_deterministic(Assertion(kind, value), text) is expected


class TestRunner:
    async def test_a_case_runs_once_with_the_skill_and_once_without(self):
        model = ScriptedModel()
        runner = EvalRunner(model)

        await runner.run_case(_case(Assertion("contains", "with")), "SKILL BODY")

        assert [system for system, _ in model.calls] == ["SKILL BODY", BASELINE_SYSTEM]

    async def test_the_delta_isolates_the_skill(self):
        runner = EvalRunner(SystemAwareModel())

        result = await runner.run_case(_case(Assertion("contains", "rollback")), "SKILL BODY")

        assert result.with_skill.pass_rate == 1.0
        assert result.without_skill.pass_rate == 0.0
        assert result.delta == 1.0
        assert result.passed

    async def test_a_skill_that_changes_nothing_scores_zero_delta(self):
        runner = EvalRunner(ScriptedModel(["same answer"]))

        result = await runner.run_case(_case(Assertion("contains", "same")), "SKILL BODY")

        assert result.passed
        assert result.delta == 0.0

    async def test_repeat_asks_more_than_once_per_variant(self):
        model = ScriptedModel(["a", "a", "a", "a", "a", "a"])
        runner = EvalRunner(model)

        await runner.run_case(_case(Assertion("contains", "a"), repeat=3), "S")

        assert len(model.calls) == 6

    async def test_threshold_lets_a_case_survive_one_bad_sample(self):
        model = ScriptedModel(["good", "bad", "good", "x", "x", "x"])
        runner = EvalRunner(model)

        result = await runner.run_case(
            _case(Assertion("contains", "good"), repeat=3, threshold=0.66), "S"
        )

        assert result.with_skill.pass_rate == pytest.approx(2 / 3)
        assert result.passed

    async def test_a_case_below_its_threshold_fails(self):
        model = ScriptedModel(["good", "bad", "bad", "x", "x", "x"])
        runner = EvalRunner(model)

        result = await runner.run_case(
            _case(Assertion("contains", "good"), repeat=3, threshold=0.66), "S"
        )

        assert not result.passed

    async def test_unmet_assertions_are_recorded(self):
        runner = EvalRunner(ScriptedModel(["nothing useful"]))

        result = await runner.run_case(_case(Assertion("contains", "rollback")), "S")

        [unmet] = [a for a in result.with_skill.attempts[0].assertions if not a.passed]
        assert unmet.assertion.value == "rollback"


class TestJudgedAssertions:
    async def test_a_pass_verdict_passes(self):
        judge = ScriptedModel(["PASS"], model_id="judge")
        runner = EvalRunner(ScriptedModel(["some answer"]), judge=judge)

        result = await runner.run_case(_case(Assertion("judge", "is helpful")), "S")

        assert result.with_skill.attempts[0].passed
        assert "is helpful" in judge.calls[0][1]

    async def test_anything_but_pass_fails(self):
        runner = EvalRunner(ScriptedModel(["answer"]), judge=ScriptedModel(["FAIL"]))

        result = await runner.run_case(_case(Assertion("judge", "is helpful")), "S")

        assert not result.with_skill.attempts[0].passed

    async def test_the_model_judges_itself_when_no_judge_is_given(self):
        model = ScriptedModel(["PASS"])
        runner = EvalRunner(model)

        await runner.run_case(_case(Assertion("judge", "is helpful")), "S")

        assert any("Claim: is helpful" in prompt for _, prompt in model.calls)


class TestAgreement:
    def test_unanimous_repeats_agree_completely(self):
        attempts = [AttemptResult("a", [AssertionResult(Assertion("contains", "a"), True)])] * 3

        assert VariantResult(attempts).agreement == 1.0

    def test_a_split_verdict_shows_as_disagreement(self):
        good = AttemptResult("a", [AssertionResult(Assertion("contains", "a"), True)])
        bad = AttemptResult("b", [AssertionResult(Assertion("contains", "a"), False)])

        assert VariantResult([good, bad]).agreement == 0.5

    def test_no_attempts_is_a_zero_pass_rate_and_full_agreement(self):
        empty = VariantResult([])

        assert empty.pass_rate == 0.0
        assert empty.agreement == 1.0


class TestCache:
    async def test_a_second_run_does_not_call_the_model(self, tmp_path: Path):
        case = _case(Assertion("contains", "with"))
        first = ScriptedModel()
        await EvalRunner(first, cache=CompletionCache(tmp_path)).run_case(case, "S")

        second = ScriptedModel()
        await EvalRunner(second, cache=CompletionCache(tmp_path)).run_case(case, "S")

        assert first.calls
        assert second.calls == []

    async def test_editing_the_skill_invalidates_the_cache(self, tmp_path: Path):
        case = _case(Assertion("contains", "with"))
        await EvalRunner(ScriptedModel(), cache=CompletionCache(tmp_path)).run_case(case, "S")

        model = ScriptedModel()
        await EvalRunner(model, cache=CompletionCache(tmp_path)).run_case(case, "EDITED")

        # The baseline half is unchanged and still cached; only the
        # "with skill" half has to be bought again.
        assert [system for system, _ in model.calls] == ["EDITED"]

    async def test_editing_an_assertion_regrades_rather_than_rebuys(self, tmp_path: Path):
        await EvalRunner(ScriptedModel(), cache=CompletionCache(tmp_path)).run_case(
            _case(Assertion("contains", "with")), "S"
        )

        model = ScriptedModel()
        result = await EvalRunner(model, cache=CompletionCache(tmp_path)).run_case(
            _case(Assertion("contains", "skill")), "S"
        )

        assert model.calls == []
        assert result.with_skill.attempts[0].passed

    async def test_a_disabled_cache_never_reuses(self):
        case = _case(Assertion("contains", "with"))
        await EvalRunner(ScriptedModel(), cache=CompletionCache(None)).run_case(case, "S")

        model = ScriptedModel()
        await EvalRunner(model, cache=CompletionCache(None)).run_case(case, "S")

        assert len(model.calls) == 2

    def test_a_corrupt_entry_is_a_miss(self, tmp_path: Path):
        cache = CompletionCache(tmp_path)
        key = CompletionCache.key("m", "s", "p", 0)
        (tmp_path / f"{key}.json").write_text("{not json", encoding="utf-8")

        assert cache.get(key) is None

    def test_an_entry_without_text_is_a_miss(self, tmp_path: Path):
        cache = CompletionCache(tmp_path)
        key = CompletionCache.key("m", "s", "p", 0)
        (tmp_path / f"{key}.json").write_text("{}", encoding="utf-8")

        assert cache.get(key) is None

    def test_an_unwritable_cache_does_not_fail_the_run(self, tmp_path: Path):
        blocker = tmp_path / "file"
        blocker.write_text("not a directory", encoding="utf-8")
        cache = CompletionCache(blocker / "cache")

        cache.put(CompletionCache.key("m", "s", "p", 0), ModelResponse("x"))

        assert cache.misses == 1

    def test_repeats_are_cached_separately(self):
        first = CompletionCache.key("m", "s", "p", 0)
        second = CompletionCache.key("m", "s", "p", 1)

        assert first != second

    def test_the_model_is_part_of_the_key(self):
        assert CompletionCache.key("a", "s", "p", 0) != CompletionCache.key("b", "s", "p", 0)


class TestLoadModel:
    @pytest.fixture
    def fake_module(self, monkeypatch):
        module = types.ModuleType("fake_eval_client")
        monkeypatch.setitem(sys.modules, "fake_eval_client", module)
        return module

    def test_resolves_a_factory(self, fake_module):
        fake_module.make = lambda: ScriptedModel()

        assert load_model("fake_eval_client:make").model_id == "scripted"

    @pytest.mark.parametrize("spec", ["", "module_only", ":factory_only"])
    def test_a_malformed_spec_is_rejected(self, spec: str):
        with pytest.raises(CliError, match="module:factory"):
            load_model(spec)

    def test_an_unimportable_module_is_reported(self):
        with pytest.raises(CliError, match="cannot import"):
            load_model("no_such_module_at_all:make")

    def test_a_missing_factory_is_reported(self, fake_module):
        with pytest.raises(CliError, match="no attribute"):
            load_model("fake_eval_client:absent")

    def test_something_that_is_not_a_model_is_reported(self, fake_module):
        fake_module.make = lambda: object()

        with pytest.raises(CliError, match="ten-line adapter"):
            load_model("fake_eval_client:make")


class TestReporting:
    async def _results(self) -> list[SuiteResult]:
        suite = _suite(_case(Assertion("contains", "rollback"), name="triage"))
        runner = EvalRunner(SystemAwareModel())
        return await run_suites(runner, [(suite, "SKILL BODY")])

    async def test_text_report_shows_both_halves_and_the_delta(self):
        out = io.StringIO()

        render_results_text(await self._results(), out)

        text = out.getvalue()
        assert "with 100%, without 0%, delta +100%" in text
        assert "1 case run, 0 failed" in text

    async def test_text_report_lists_unmet_assertions(self):
        suite = _suite(_case(Assertion("contains", "nope"), name="triage"))
        results = await run_suites(EvalRunner(ScriptedModel()), [(suite, "S")])
        out = io.StringIO()

        render_results_text(results, out)

        assert "unmet contains: nope" in out.getvalue()
        assert "FAIL" in out.getvalue()

    async def test_text_report_flags_disagreeing_repeats(self):
        suite = _suite(_case(Assertion("contains", "good"), repeat=2, threshold=0.5))
        model = ScriptedModel(["good", "bad", "x", "x"])
        results = await run_suites(EvalRunner(model), [(suite, "S")])
        out = io.StringIO()

        render_results_text(results, out)

        assert "repeats disagreed (50% agreement)" in out.getvalue()

    async def test_json_report_is_serialisable_and_complete(self):
        payload = results_payload(await self._results())

        assert json.dumps(payload)
        assert payload["ok"] is True
        assert payload["meanDelta"] == 1.0
        [entry] = payload["suites"]
        assert entry["skill"] == "demo"
        assert entry["model"] == "system-aware"
        [case] = entry["cases"]
        assert case["withSkill"] == 1.0
        assert case["withoutSkill"] == 0.0
        assert case["unmet"] == []

    def test_an_empty_run_reports_nothing_rather_than_dividing_by_zero(self):
        out = io.StringIO()

        render_results_text([], out)

        assert "0 cases run" in out.getvalue()
        assert results_payload([])["meanDelta"] == 0.0

    def test_a_suite_with_no_cases_has_no_delta(self):
        assert SuiteResult(_suite(), "m").delta == 0.0
        assert SuiteResult(_suite(), "m").passed

    async def test_exit_code_follows_the_cases(self):
        assert eval_exit_code(await self._results()) == 0

        suite = _suite(_case(Assertion("contains", "nope")))
        failing = await run_suites(EvalRunner(ScriptedModel()), [(suite, "S")])
        assert eval_exit_code(failing) == 1
