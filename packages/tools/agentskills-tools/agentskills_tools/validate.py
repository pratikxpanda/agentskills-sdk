"""``agentskills validate`` — spec conformance, exit code as the contract.

Diagnosis happens in two stages.  Frontmatter is parsed here first,
because :func:`~agentskills_core.split_frontmatter` is deliberately
forgiving — malformed YAML yields an empty mapping rather than an
exception, which downstream reads as "no name, no description" and
tells the author nothing about the colon they missed.  Only once the
frontmatter parses is the skill handed to
:func:`~agentskills_core.validate_skill`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agentskills_core import Skill, get_logger, validate_skill
from agentskills_core.parsing import MAX_FRONTMATTER_BYTES
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_tools.discovery import SKILL_FILE, SkillLocation
from agentskills_tools.evalspec import check_skill_evals
from agentskills_tools.findings import ERROR, Finding, SkillReport

_logger = get_logger(__name__)


def _yaml_detail(exc: yaml.YAMLError) -> tuple[str, int | None]:
    """Reduce a YAML error to a one-line reason and a ``SKILL.md`` line."""
    problem = getattr(exc, "problem", None)
    mark = getattr(exc, "problem_mark", None)
    reason = problem or str(exc).splitlines()[0]
    # The mark is relative to the block, whose first line is the one
    # after the opening '---'.
    line = mark.line + 1 if mark is not None else None
    return reason, line


def check_frontmatter(text: str) -> list[Finding]:
    """Report why the frontmatter of *text* cannot be parsed, if it cannot.

    Args:
        text: Full contents of a ``SKILL.md``.

    Returns:
        Findings describing the first structural problem found, or an
        empty list when the frontmatter is a well-formed mapping.
    """
    if not text.startswith("---"):
        return [
            Finding(
                ERROR,
                "frontmatter-missing",
                f"{SKILL_FILE} must open with a '---' frontmatter delimiter",
                line=1,
            )
        ]

    end = text.find("---", 3)
    if end == -1:
        return [
            Finding(
                ERROR,
                "frontmatter-unclosed",
                "the frontmatter block is never closed with '---'",
                line=1,
            )
        ]

    block = text[3:end]
    if len(block.strip().encode("utf-8", errors="replace")) > MAX_FRONTMATTER_BYTES:
        return [
            Finding(
                ERROR,
                "frontmatter-too-large",
                f"frontmatter exceeds {MAX_FRONTMATTER_BYTES} bytes and will be ignored entirely",
                line=1,
            )
        ]

    try:
        parsed = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        reason, line = _yaml_detail(exc)
        return [
            Finding(
                ERROR,
                "frontmatter-invalid-yaml",
                f"frontmatter is not valid YAML: {reason}",
                line,
            )
        ]

    if parsed is not None and not isinstance(parsed, dict):
        return [
            Finding(
                ERROR,
                "frontmatter-not-a-mapping",
                f"frontmatter must be a mapping of fields, not {type(parsed).__name__}",
                line=2,
            )
        ]

    return []


def read_skill_md(path: Path) -> str:
    """Return the text of the ``SKILL.md`` in skill directory *path*.

    Raises:
        OSError: If the file is missing or unreadable.
        ValueError: If it is not valid UTF-8.
    """
    return path.joinpath(SKILL_FILE).read_text(encoding="utf-8")


def unreadable(exc: Exception) -> Finding:
    """Wrap a failed :func:`read_skill_md` as a finding."""
    return Finding(ERROR, "unreadable", f"cannot read {SKILL_FILE}: {exc}")


async def validate_location(root: Path, location: SkillLocation) -> SkillReport:
    """Validate one skill and return its report."""
    try:
        text = read_skill_md(location.path)
    except (OSError, ValueError) as exc:
        return SkillReport(location.skill_id, location.path, [unreadable(exc)])

    findings = check_frontmatter(text)
    if findings:
        # Spec checks read through the same forgiving parser, so they
        # would only restate the damage in less useful terms.  Eval
        # files are a separate document and stay worth checking.
        findings.extend(check_skill_evals(location.path, location.skill_id))
        return SkillReport(location.skill_id, location.path, findings)

    skill = Skill(location.skill_id, LocalFileSystemSkillProvider(root))
    prefix = f"Skill '{location.skill_id}': "
    findings = [
        Finding(ERROR, "spec", message.removeprefix(prefix))
        for message in await validate_skill(skill)
    ]
    # Eval cases are checked here, with no model and no API key, so a
    # broken one fails beside the skill it belongs to rather than the
    # first time somebody pays to run it.
    findings.extend(check_skill_evals(location.path, location.skill_id))
    _logger.debug("Validated %s: %d findings", location.skill_id, len(findings))
    return SkillReport(location.skill_id, location.path, findings)


async def validate_locations(root: Path, locations: list[SkillLocation]) -> list[SkillReport]:
    """Validate every discovered skill, in ID order."""
    return [await validate_location(root, location) for location in locations]
