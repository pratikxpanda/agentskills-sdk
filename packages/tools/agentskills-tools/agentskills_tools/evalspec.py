"""The eval case file format, parsed and checked without running anything.

A skill is a prompt, and nobody measures whether a given prompt makes an
agent better.  Eval cases are how a skill states what it is *for* in a
form something can check::

    # my-skill/evals/rollback.yaml
    skill: deploy-rollback
    judge_model: gpt-4o
    cases:
      - name: after-a-bad-deploy
        prompt: "Production is erroring after the 14:02 deploy."
        expect:
          - contains: "kubectl rollout undo"
          - not_contains: "kubectl delete"
          - judge: "Recommends rollback before investigating root cause"

Parsing lives here rather than in the runner so that ``agentskills
validate`` can check a suite without an API key, a model, or a bill.
A malformed eval file is a broken test, and a broken test should fail in
CI beside the skill it belongs to, not the first time somebody pays to
run it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from agentskills_tools.discovery import relative_to_cwd
from agentskills_tools.findings import ERROR, Finding

#: Directory inside a skill folder holding its eval suites.
EVALS_DIR = "evals"

#: Assertions checked against the model's answer with no second model.
DETERMINISTIC_KINDS: frozenset[str] = frozenset({"contains", "not_contains", "regex"})

#: Assertions handed to a judge model.
JUDGED_KINDS: frozenset[str] = frozenset({"judge"})

ASSERTION_KINDS: frozenset[str] = DETERMINISTIC_KINDS | JUDGED_KINDS


@dataclass(frozen=True)
class Assertion:
    """One expectation about a model's answer.

    Attributes:
        kind: One of :data:`ASSERTION_KINDS`.
        value: The substring, pattern, or judged claim.
    """

    kind: str
    value: str

    @property
    def judged(self) -> bool:
        """``True`` when checking this needs a judge model."""
        return self.kind in JUDGED_KINDS

    def describe(self) -> str:
        """Return a one-line description for a report."""
        return f"{self.kind}: {self.value}"


@dataclass(frozen=True)
class EvalCase:
    """One prompt and everything expected of the answer.

    Attributes:
        name: Identifier, unique within the suite.
        prompt: The user turn sent to the model.
        expect: Assertions that must hold.
        repeat: How many times to ask.  Models are not deterministic
            even at temperature zero, so a single sample is a coin
            toss dressed as a measurement.
        threshold: Fraction of repeats that must pass for the case to
            pass.  ``1.0`` means every repeat.
    """

    name: str
    prompt: str
    expect: list[Assertion]
    repeat: int = 1
    threshold: float = 1.0

    @property
    def needs_judge(self) -> bool:
        """``True`` when any assertion needs a judge model."""
        return any(assertion.judged for assertion in self.expect)


@dataclass(frozen=True)
class EvalSuite:
    """Every case in one eval file.

    Attributes:
        path: The file the suite was read from.
        skill_id: The skill under test.
        cases: The cases, in file order.
        judge_model: Model name recorded for judged assertions.  An LLM
            judge is itself unreliable, so which one judged a run is
            part of the result, not an implementation detail.
    """

    path: Path
    skill_id: str
    cases: list[EvalCase]
    judge_model: str | None = None

    @property
    def needs_judge(self) -> bool:
        """``True`` when any case needs a judge model."""
        return any(case.needs_judge for case in self.cases)


def find_suites(skill_dir: Path) -> list[Path]:
    """Return the eval files under *skill_dir*, sorted.

    Args:
        skill_dir: A skill folder.

    Returns:
        Every ``.yaml`` or ``.yml`` file directly inside ``evals/``.
        Dotted files are skipped, matching the provider's rules for
        every other resource directory.
    """
    evals = skill_dir / EVALS_DIR
    if not evals.is_dir():
        return []
    return sorted(
        entry
        for entry in evals.iterdir()
        if entry.is_file() and not entry.name.startswith(".") and entry.suffix in {".yaml", ".yml"}
    )


def _finding(code: str, message: str, path: Path, line: int | None = None) -> Finding:
    return Finding(ERROR, code, message, line, relative_to_cwd(path))


def _parse_assertion(raw: object, path: Path, where: str) -> tuple[Assertion | None, list[Finding]]:
    """Turn one ``expect`` entry into an assertion."""
    if not isinstance(raw, dict):
        return None, [
            _finding(
                "eval-assertion-not-a-mapping",
                f"{where}: each expectation must be a mapping like "
                f"'- contains: text', not {type(raw).__name__}",
                path,
            )
        ]
    if len(raw) != 1:
        return None, [
            _finding(
                "eval-assertion-not-single-keyed",
                f"{where}: each expectation must carry exactly one of "
                f"{', '.join(sorted(ASSERTION_KINDS))}, got {len(raw)} keys",
                path,
            )
        ]

    kind, value = next(iter(raw.items()))
    if kind not in ASSERTION_KINDS:
        return None, [
            _finding(
                "eval-unknown-assertion",
                f"{where}: unknown expectation '{kind}'; expected one of "
                f"{', '.join(sorted(ASSERTION_KINDS))}",
                path,
            )
        ]
    if not isinstance(value, str) or not value.strip():
        return None, [
            _finding(
                "eval-empty-assertion",
                f"{where}: '{kind}' needs a non-empty string",
                path,
            )
        ]
    if kind == "regex":
        try:
            re.compile(value)
        except re.error as exc:
            return None, [
                _finding(
                    "eval-invalid-regex",
                    f"{where}: regex does not compile: {exc}",
                    path,
                )
            ]

    return Assertion(kind, value), []


def _parse_case(raw: object, index: int, path: Path) -> tuple[EvalCase | None, list[Finding]]:
    """Turn one ``cases`` entry into a case."""
    where = f"case {index + 1}"
    if not isinstance(raw, dict):
        return None, [
            _finding(
                "eval-case-not-a-mapping",
                f"{where}: each case must be a mapping, not {type(raw).__name__}",
                path,
            )
        ]

    name = raw.get("name", f"case-{index + 1}")
    if not isinstance(name, str) or not name.strip():
        return None, [_finding("eval-invalid-case-name", f"{where}: name must be text", path)]
    where = f"case '{name}'"

    findings: list[Finding] = []
    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        findings.append(
            _finding("eval-missing-prompt", f"{where}: needs a non-empty 'prompt'", path)
        )

    expect_raw = raw.get("expect")
    if not isinstance(expect_raw, list) or not expect_raw:
        findings.append(
            _finding(
                "eval-no-assertions",
                f"{where}: needs a non-empty 'expect' list; a case that asserts "
                f"nothing cannot fail, and a test that cannot fail measures nothing",
                path,
            )
        )
        expect_raw = []

    expect: list[Assertion] = []
    for entry in expect_raw:
        assertion, problems = _parse_assertion(entry, path, where)
        findings.extend(problems)
        if assertion is not None:
            expect.append(assertion)

    repeat = raw.get("repeat", 1)
    if not isinstance(repeat, int) or isinstance(repeat, bool) or repeat < 1:
        findings.append(
            _finding("eval-invalid-repeat", f"{where}: 'repeat' must be an integer >= 1", path)
        )
        repeat = 1

    threshold = raw.get("threshold", 1.0)
    if isinstance(threshold, bool) or not isinstance(threshold, int | float):
        findings.append(
            _finding("eval-invalid-threshold", f"{where}: 'threshold' must be a number", path)
        )
        threshold = 1.0
    elif not 0 < threshold <= 1:
        findings.append(
            _finding(
                "eval-invalid-threshold",
                f"{where}: 'threshold' must be greater than 0 and at most 1; "
                f"a threshold of 0 passes a case nothing satisfied",
                path,
            )
        )
        threshold = 1.0

    if findings:
        return None, findings
    return EvalCase(name, prompt, expect, repeat, float(threshold)), []


def load_suite(path: Path, skill_id: str) -> tuple[EvalSuite | None, list[Finding]]:
    """Read and check one eval file.

    Args:
        path: The eval file.
        skill_id: The skill whose folder holds it.

    Returns:
        ``(suite, findings)``.  *suite* is ``None`` when anything was
        wrong, so a caller cannot half-run a broken file.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return None, [_finding("eval-unreadable", f"cannot read eval file: {exc}", path)]

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        reason = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        line = mark.line + 1 if mark is not None else None
        return None, [_finding("eval-invalid-yaml", f"not valid YAML: {reason}", path, line)]

    if not isinstance(document, dict):
        kind = "nothing" if document is None else type(document).__name__
        return None, [
            _finding("eval-not-a-mapping", f"an eval file must be a mapping, got {kind}", path)
        ]

    findings: list[Finding] = []

    declared = document.get("skill")
    if declared is not None and declared != skill_id:
        findings.append(
            _finding(
                "eval-skill-mismatch",
                f"declares skill '{declared}' but sits in the folder for '{skill_id}'",
                path,
            )
        )

    judge_model = document.get("judge_model")
    if judge_model is not None and (not isinstance(judge_model, str) or not judge_model.strip()):
        findings.append(_finding("eval-invalid-judge-model", "'judge_model' must be text", path))
        judge_model = None

    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        findings.append(_finding("eval-no-cases", "needs a non-empty 'cases' list", path))
        raw_cases = []

    cases: list[EvalCase] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_cases):
        case, problems = _parse_case(raw, index, path)
        findings.extend(problems)
        if case is None:
            continue
        if case.name in seen:
            findings.append(
                _finding(
                    "eval-duplicate-case-name",
                    f"case '{case.name}' is defined more than once",
                    path,
                )
            )
            continue
        seen.add(case.name)
        cases.append(case)

    if any(case.needs_judge for case in cases) and not judge_model:
        findings.append(
            _finding(
                "eval-judge-model-missing",
                "a 'judge' expectation needs a 'judge_model' at the top level; "
                "which model judged a run is part of the result",
                path,
            )
        )

    if findings:
        return None, findings
    return EvalSuite(path, skill_id, cases, judge_model), []


def check_skill_evals(skill_dir: Path, skill_id: str) -> list[Finding]:
    """Return every problem in the eval files of one skill."""
    findings: list[Finding] = []
    for path in find_suites(skill_dir):
        _, problems = load_suite(path, skill_id)
        findings.extend(problems)
    return findings


def load_skill_evals(skill_dir: Path, skill_id: str) -> tuple[list[EvalSuite], list[Finding]]:
    """Return the loadable suites of one skill, and the problems found."""
    suites: list[EvalSuite] = []
    findings: list[Finding] = []
    for path in find_suites(skill_dir):
        suite, problems = load_suite(path, skill_id)
        findings.extend(problems)
        if suite is not None:
            suites.append(suite)
    return suites, findings
