"""``agentskills lint`` — quality warnings that are not spec violations.

Everything here is legal per the specification and still likely to cost
the author something: a description too long to sit comfortably in a
catalog, a body that eats the context window, a script nobody is told
to run.
"""

from __future__ import annotations

from pathlib import Path

from agentskills_core import (
    RESOURCE_KINDS,
    SELECTION_FIELDS,
    Skill,
    estimate_tokens,
    get_logger,
)
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_tools.discovery import SkillLocation
from agentskills_tools.findings import WARNING, Finding, SkillReport
from agentskills_tools.validate import check_frontmatter, read_skill_md, unreadable

__all__ = ["estimate_tokens"]

# Every catalog entry is injected into the system prompt on every turn,
# so a description is charged for far more often than a body is.
CATALOG_DESCRIPTION_CHARS = 500

# Past this, a description has usually stopped being a summary and started
# smuggling conditions — "use for X, but not Y, unless Z" — which is what
# when_to_use and when_not_to_use are for.
SELECTION_METADATA_DESCRIPTION_CHARS = 200

DEFAULT_BODY_TOKEN_BUDGET = 5000

_logger = get_logger(__name__)


async def lint_location(
    root: Path,
    location: SkillLocation,
    *,
    body_token_budget: int = DEFAULT_BODY_TOKEN_BUDGET,
) -> SkillReport:
    """Lint one skill and return its report.

    Args:
        root: Provider root the skill lives under.
        location: The skill to lint.
        body_token_budget: Estimated token count above which the body is
            reported as oversized.

    Returns:
        A report whose findings are warnings, unless the skill could not
        be parsed at all — an unreadable or malformed skill is reported
        as an error, because linting it would mean guessing.
    """
    try:
        text = read_skill_md(location.path)
    except (OSError, ValueError) as exc:
        return SkillReport(location.skill_id, location.path, [unreadable(exc)])

    blocking = check_frontmatter(text)
    if blocking:
        return SkillReport(location.skill_id, location.path, blocking)

    skill = Skill(location.skill_id, LocalFileSystemSkillProvider(root))
    metadata = await skill.get_metadata()
    body = await skill.get_body()

    findings: list[Finding] = []

    if not metadata.get("version"):
        findings.append(
            Finding(
                WARNING,
                "missing-version",
                "no 'version' field, so consumers cannot pin this skill or detect drift",
            )
        )

    description = metadata.get("description")
    if isinstance(description, str) and len(description) > CATALOG_DESCRIPTION_CHARS:
        findings.append(
            Finding(
                WARNING,
                "description-too-long-for-catalog",
                f"description is {len(description)} characters; "
                f"catalog entries stay in context every turn, so keep it under "
                f"{CATALOG_DESCRIPTION_CHARS}",
            )
        )

    if (
        isinstance(description, str)
        and len(description) > SELECTION_METADATA_DESCRIPTION_CHARS
        and not any(key in metadata for key in SELECTION_FIELDS)
    ):
        findings.append(
            Finding(
                WARNING,
                "missing-selection-metadata",
                f"description is {len(description)} characters and the skill declares "
                f"neither 'when_to_use' nor 'when_not_to_use'; state the boundary in "
                f"those fields instead of folding it into the description",
            )
        )

    tokens = estimate_tokens(body)
    if tokens > body_token_budget:
        findings.append(
            Finding(
                WARNING,
                "body-over-token-budget",
                f"body is roughly {tokens} tokens, over the {body_token_budget} budget; "
                f"move detail into references/ so it loads only when needed",
            )
        )

    findings.extend(await _unreferenced_resources(skill, body))

    _logger.debug("Linted %s: %d findings", location.skill_id, len(findings))
    return SkillReport(location.skill_id, location.path, findings)


async def _unreferenced_resources(skill: Skill, body: str) -> list[Finding]:
    """Warn about resource files the body never mentions.

    An agent only reaches a reference, script, or asset if the body
    tells it to, so a file nobody names is a file nobody loads.
    """
    if not skill.supports_resource_listing:
        return []

    resources = await skill.list_resources()
    return [
        Finding(
            WARNING,
            "unreferenced-resource",
            f"{kind}/{name} is never mentioned in the body, so an agent will not know to load it",
        )
        for kind in RESOURCE_KINDS
        for name in resources.get(kind, [])
        if name not in body
    ]


async def lint_locations(
    root: Path,
    locations: list[SkillLocation],
    *,
    body_token_budget: int = DEFAULT_BODY_TOKEN_BUDGET,
) -> list[SkillReport]:
    """Lint every discovered skill, in ID order."""
    return [
        await lint_location(root, location, body_token_budget=body_token_budget)
        for location in locations
    ]
