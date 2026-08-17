"""``agentskills eval`` — measure what difference a skill actually makes.

Every case runs twice: once with the skill's body in the system prompt
and once without.  Absolute pass rates mostly measure the model, so the
number that means anything is the difference between the two.  A skill
whose cases pass equally well without it is not earning its tokens.

Model access is a :class:`EvalModel` protocol with one method, resolved
at run time from a dotted path::

    agentskills eval ./skills --model mypkg.evals:openai_client

Nothing here imports an LLM SDK, and nothing anywhere in this project
depends on one.  A ten-line adapter is a smaller ask than an opinion
about which vendor everybody should install.

Completions are cached on disk by everything that determined them, so
re-running after editing an assertion re-reads the answer instead of
re-buying it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, TextIO, runtime_checkable

from agentskills_core import get_logger
from agentskills_tools.discovery import CliError
from agentskills_tools.evalspec import Assertion, EvalCase, EvalSuite

_logger = get_logger(__name__)

#: Where completions are cached unless the caller says otherwise.
DEFAULT_CACHE_DIR = Path(".agentskills") / "eval-cache"

#: System prompt for the run without the skill.  Empty on purpose: the
#: baseline is the model as it ships, which is what the skill has to beat.
BASELINE_SYSTEM = ""

#: What the judge is told.  It answers one token so a wrong answer is
#: obvious rather than buried in prose.
JUDGE_SYSTEM = (
    "You grade another assistant's answer against a single claim. "
    "Reply with exactly one word: PASS if the claim is true of the answer, "
    "FAIL if it is not."
)


@dataclass(frozen=True)
class ModelResponse:
    """What a model returned.

    Attributes:
        text: The assistant's answer.
    """

    text: str


@runtime_checkable
class EvalModel(Protocol):
    """The whole model contract: a name, and a way to ask it something.

    Implement it over any client::

        class OpenAIModel:
            model_id = "gpt-4o"

            async def complete(self, *, system: str, prompt: str) -> ModelResponse:
                reply = await client.chat.completions.create(...)
                return ModelResponse(reply.choices[0].message.content or "")

    ``model_id`` is part of the cache key and of every report, because a
    pass rate without the model that produced it is not a measurement.
    Set temperature to zero in the adapter if the provider allows it;
    this side has no opinion it could enforce.
    """

    model_id: str

    async def complete(self, *, system: str, prompt: str) -> ModelResponse:
        """Return the model's answer to *prompt* under *system*."""
        ...


def load_model(spec: str) -> EvalModel:
    """Resolve ``module:factory`` to a model client.

    Args:
        spec: A dotted module path, a colon, and the name of a zero-
            argument callable returning an :class:`EvalModel`.

    Returns:
        The client the factory built.

    Raises:
        CliError: If the spec is malformed, cannot be imported, or does
            not produce something with ``model_id`` and ``complete``.
    """
    module_name, _, factory_name = spec.partition(":")
    if not module_name or not factory_name:
        raise CliError(f"--model must look like 'module:factory', got {spec!r}")

    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise CliError(f"cannot import '{module_name}': {exc}") from exc

    try:
        factory = getattr(module, factory_name)
    except AttributeError as exc:
        raise CliError(f"'{module_name}' has no attribute '{factory_name}'") from exc

    client = factory()
    if not isinstance(client, EvalModel):
        raise CliError(
            f"{spec} returned {type(client).__name__}, which has no 'model_id' "
            f"and 'complete'. See the eval docs for a ten-line adapter."
        )
    return client


class CompletionCache:
    """Completions on disk, keyed by everything that determined them.

    The key covers the model, the system prompt (which carries the skill
    body, so editing a skill invalidates its runs), the user prompt, and
    the repeat index.  It deliberately does **not** cover the
    assertions: tightening an expectation should re-grade the answers
    already bought, not buy them again.
    """

    def __init__(self, directory: Path | None) -> None:
        """Create a cache, or a disabled one when *directory* is ``None``."""
        self._directory = directory
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(model_id: str, system: str, prompt: str, attempt: int) -> str:
        """Return the cache key for one completion."""
        digest = hashlib.sha256()
        for part in (model_id, system, prompt, str(attempt)):
            digest.update(part.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()

    def get(self, key: str) -> ModelResponse | None:
        """Return the cached completion for *key*, if there is one."""
        if self._directory is None:
            return None
        path = self._directory / f"{key}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            text = payload["text"]
        except (OSError, ValueError, KeyError):
            # A corrupt or half-written entry is a cache miss, not a
            # failed run; the answer is one request away.
            return None
        self.hits += 1
        return ModelResponse(str(text))

    def put(self, key: str, response: ModelResponse) -> None:
        """Store *response* under *key*, best-effort."""
        self.misses += 1
        if self._directory is None:
            return
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            (self._directory / f"{key}.json").write_text(
                json.dumps({"text": response.text}), encoding="utf-8"
            )
        except OSError as exc:
            _logger.debug("Could not write eval cache entry: %s", exc)


@dataclass(frozen=True)
class AssertionResult:
    """Whether one assertion held for one answer."""

    assertion: Assertion
    passed: bool


@dataclass(frozen=True)
class AttemptResult:
    """One answer and how it scored."""

    text: str
    assertions: list[AssertionResult]

    @property
    def passed(self) -> bool:
        """``True`` when every assertion held."""
        return all(result.passed for result in self.assertions)


@dataclass(frozen=True)
class VariantResult:
    """Every repeat of one case, in one variant."""

    attempts: list[AttemptResult]

    @property
    def pass_rate(self) -> float:
        """Fraction of repeats where every assertion held."""
        if not self.attempts:
            return 0.0
        return sum(attempt.passed for attempt in self.attempts) / len(self.attempts)

    @property
    def agreement(self) -> float:
        """How much the repeats agreed with each other.

        ``1.0`` means every repeat reached the same verdict.  A case
        that passes three times out of five has not measured a skill;
        it has measured sampling noise, and this is the number that
        says so.
        """
        if not self.attempts:
            return 1.0
        rate = self.pass_rate
        return max(rate, 1.0 - rate)


@dataclass(frozen=True)
class CaseResult:
    """One case, run both ways."""

    case: EvalCase
    with_skill: VariantResult
    without_skill: VariantResult

    @property
    def passed(self) -> bool:
        """``True`` when the run with the skill met the threshold."""
        return self.with_skill.pass_rate >= self.case.threshold

    @property
    def delta(self) -> float:
        """Pass rate with the skill, minus the pass rate without it."""
        return self.with_skill.pass_rate - self.without_skill.pass_rate


@dataclass
class SuiteResult:
    """Every case in one suite."""

    suite: EvalSuite
    model_id: str
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """``True`` when every case met its threshold."""
        return all(case.passed for case in self.cases)

    @property
    def delta(self) -> float:
        """Mean per-case delta across the suite."""
        if not self.cases:
            return 0.0
        return sum(case.delta for case in self.cases) / len(self.cases)


def check_deterministic(assertion: Assertion, text: str) -> bool:
    """Return whether a non-judged *assertion* holds for *text*."""
    if assertion.kind == "contains":
        return assertion.value in text
    if assertion.kind == "not_contains":
        return assertion.value not in text
    return re.search(assertion.value, text) is not None


class EvalRunner:
    """Runs suites against a model, twice per case."""

    def __init__(
        self,
        model: EvalModel,
        *,
        judge: EvalModel | None = None,
        cache: CompletionCache | None = None,
    ) -> None:
        """Create a runner.

        Args:
            model: The model under test.
            judge: Model used for judged assertions.  Defaults to
                *model*, which is worth knowing about: a model grading
                its own answer is the cheapest judge and the least
                independent one.
            cache: Completion cache.  Defaults to a disabled cache.
        """
        self._model = model
        self._judge = judge or model
        self._cache = cache or CompletionCache(None)

    async def _complete(self, model: EvalModel, system: str, prompt: str, attempt: int) -> str:
        key = CompletionCache.key(model.model_id, system, prompt, attempt)
        cached = self._cache.get(key)
        if cached is not None:
            return cached.text
        response = await model.complete(system=system, prompt=prompt)
        self._cache.put(key, response)
        return response.text

    async def _judge_claim(self, claim: str, answer: str) -> bool:
        prompt = f"Claim: {claim}\n\nAnswer to grade:\n{answer}"
        verdict = await self._complete(self._judge, JUDGE_SYSTEM, prompt, 0)
        return verdict.strip().upper().startswith("PASS")

    async def _score(self, case: EvalCase, text: str) -> AttemptResult:
        results: list[AssertionResult] = []
        for assertion in case.expect:
            if assertion.judged:
                passed = await self._judge_claim(assertion.value, text)
            else:
                passed = check_deterministic(assertion, text)
            results.append(AssertionResult(assertion, passed))
        return AttemptResult(text, results)

    async def _run_variant(self, case: EvalCase, system: str) -> VariantResult:
        attempts: list[AttemptResult] = []
        for attempt in range(case.repeat):
            text = await self._complete(self._model, system, case.prompt, attempt)
            attempts.append(await self._score(case, text))
        return VariantResult(attempts)

    async def run_case(self, case: EvalCase, skill_system: str) -> CaseResult:
        """Run one case with and without the skill."""
        with_skill = await self._run_variant(case, skill_system)
        without_skill = await self._run_variant(case, BASELINE_SYSTEM)
        return CaseResult(case, with_skill, without_skill)

    async def run_suite(self, suite: EvalSuite, skill_system: str) -> SuiteResult:
        """Run every case in *suite*."""
        result = SuiteResult(suite, self._model.model_id)
        for case in suite.cases:
            result.cases.append(await self.run_case(case, skill_system))
        _logger.debug(
            "Ran %d cases from %s (cache: %d hits, %d misses)",
            len(result.cases),
            suite.path.name,
            self._cache.hits,
            self._cache.misses,
        )
        return result


async def run_suites(
    runner: EvalRunner,
    suites: list[tuple[EvalSuite, str]],
) -> list[SuiteResult]:
    """Run every ``(suite, system prompt)`` pair, in order."""
    return [await runner.run_suite(suite, system) for suite, system in suites]


def _percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def _signed_percent(value: float) -> str:
    return f"{value * 100:+.0f}%"


def render_results_text(results: list[SuiteResult], out: TextIO) -> None:
    """Write a human-readable eval report."""
    for result in results:
        print(f"{result.suite.skill_id} ({result.suite.path.name})", file=out)
        for case in result.cases:
            verdict = "pass" if case.passed else "FAIL"
            print(
                f"  {verdict:<4} {case.case.name}: "
                f"with {_percent(case.with_skill.pass_rate)}, "
                f"without {_percent(case.without_skill.pass_rate)}, "
                f"delta {_signed_percent(case.delta)}",
                file=out,
            )
            for attempt in case.with_skill.attempts[:1]:
                for assertion in attempt.assertions:
                    if not assertion.passed:
                        print(f"         unmet {assertion.assertion.describe()}", file=out)
            if case.case.repeat > 1 and case.with_skill.agreement < 1.0:
                print(
                    f"         repeats disagreed ({_percent(case.with_skill.agreement)} agreement)",
                    file=out,
                )
        print(f"  suite delta {_signed_percent(result.delta)} on {result.model_id}", file=out)

    total = sum(len(result.cases) for result in results)
    failed = sum(1 for result in results for case in result.cases if not case.passed)
    mean = sum(result.delta for result in results) / len(results) if results else 0.0
    print(
        f"\n{total} case{'' if total == 1 else 's'} run, {failed} failed, "
        f"mean delta {_signed_percent(mean)}",
        file=out,
    )


def results_payload(results: list[SuiteResult]) -> dict[str, Any]:
    """Return the machine-readable eval report."""
    return {
        "command": "eval",
        "ok": all(result.passed for result in results),
        "meanDelta": (sum(result.delta for result in results) / len(results) if results else 0.0),
        "suites": [
            {
                "skill": result.suite.skill_id,
                "file": result.suite.path.name,
                "model": result.model_id,
                "judgeModel": result.suite.judge_model,
                "delta": result.delta,
                "cases": [
                    {
                        "name": case.case.name,
                        "passed": case.passed,
                        "threshold": case.case.threshold,
                        "repeat": case.case.repeat,
                        "withSkill": case.with_skill.pass_rate,
                        "withoutSkill": case.without_skill.pass_rate,
                        "delta": case.delta,
                        "agreement": case.with_skill.agreement,
                        "unmet": [
                            assertion.assertion.describe()
                            for attempt in case.with_skill.attempts[:1]
                            for assertion in attempt.assertions
                            if not assertion.passed
                        ],
                    }
                    for case in result.cases
                ],
            }
            for result in results
        ],
    }


def eval_exit_code(results: list[SuiteResult]) -> int:
    """Return ``1`` when any case missed its threshold."""
    return 0 if all(result.passed for result in results) else 1


__all__ = [
    "BASELINE_SYSTEM",
    "DEFAULT_CACHE_DIR",
    "AssertionResult",
    "AttemptResult",
    "CaseResult",
    "CompletionCache",
    "EvalModel",
    "EvalRunner",
    "ModelResponse",
    "SuiteResult",
    "VariantResult",
    "check_deterministic",
    "eval_exit_code",
    "load_model",
    "render_results_text",
    "results_payload",
    "run_suites",
]
