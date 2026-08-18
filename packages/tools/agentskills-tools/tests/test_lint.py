"""Tests for ``agentskills lint``."""

from __future__ import annotations

from typing import Any

from agentskills_core import ResourceNotFoundError, Skill, SkillProvider
from agentskills_tools.discovery import SkillLocation
from agentskills_tools.lint import (
    CATALOG_DESCRIPTION_CHARS,
    SELECTION_METADATA_DESCRIPTION_CHARS,
    _unreferenced_resources,
    estimate_tokens,
    lint_location,
    lint_locations,
)


class _BareProvider(SkillProvider):
    """A provider that cannot enumerate — the default capability."""

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        return {}

    async def get_body(self, skill_id: str) -> str:
        return ""

    async def get_script(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(name)

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(name)

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        raise ResourceNotFoundError(name)


def _skill_md(
    *,
    description: str = "A skill.",
    version: str | None = "1.0.0",
    when_to_use: list[str] | None = None,
    body: str,
) -> str:
    lines = ["---", "name: alpha", f"description: {description}"]
    if version is not None:
        lines.append(f"version: {version}")
    if when_to_use is not None:
        lines.append("when_to_use:")
        lines += [f"  - {case}" for case in when_to_use]
    lines += ["---", "", body]
    return "\n".join(lines)


class TestEstimateTokens:
    def test_rounds_up(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens("a") == 1
        assert estimate_tokens("a" * 8) == 2


class TestLintLocation:
    async def test_clean_skill_warns_about_nothing(self, write_skill, skills_root):
        path = write_skill("alpha", _skill_md(body="Body."))

        report = await lint_location(skills_root, SkillLocation("alpha", path))

        assert report.findings == []

    async def test_missing_version(self, write_skill, skills_root):
        path = write_skill("alpha", _skill_md(version=None, body="Body."))

        report = await lint_location(skills_root, SkillLocation("alpha", path))

        assert [f.code for f in report.findings] == ["missing-version"]

    async def test_description_too_long_for_a_catalog(self, write_skill, skills_root):
        path = write_skill(
            "alpha", _skill_md(description="d" * (CATALOG_DESCRIPTION_CHARS + 1), body="Body.")
        )

        report = await lint_location(skills_root, SkillLocation("alpha", path))

        assert [f.code for f in report.findings] == [
            "description-too-long-for-catalog",
            "missing-selection-metadata",
        ]

    async def test_long_description_without_selection_metadata(self, write_skill, skills_root):
        path = write_skill(
            "alpha",
            _skill_md(description="d" * (SELECTION_METADATA_DESCRIPTION_CHARS + 1), body="Body."),
        )

        report = await lint_location(skills_root, SkillLocation("alpha", path))

        assert [f.code for f in report.findings] == ["missing-selection-metadata"]

    async def test_selection_metadata_silences_the_warning(self, write_skill, skills_root):
        path = write_skill(
            "alpha",
            _skill_md(
                description="d" * (SELECTION_METADATA_DESCRIPTION_CHARS + 1),
                when_to_use=["A production service is down"],
                body="Body.",
            ),
        )

        report = await lint_location(skills_root, SkillLocation("alpha", path))

        assert report.findings == []

    async def test_short_description_needs_no_selection_metadata(self, write_skill, skills_root):
        path = write_skill(
            "alpha", _skill_md(description="d" * SELECTION_METADATA_DESCRIPTION_CHARS, body="B.")
        )

        report = await lint_location(skills_root, SkillLocation("alpha", path))

        assert report.findings == []

    async def test_body_over_the_token_budget(self, write_skill, skills_root):
        path = write_skill("alpha", _skill_md(body="word " * 100))

        report = await lint_location(
            skills_root, SkillLocation("alpha", path), body_token_budget=10
        )

        assert [f.code for f in report.findings] == ["body-over-token-budget"]

    async def test_unreferenced_resource(self, write_skill, skills_root):
        path = write_skill("alpha", _skill_md(body="Run scripts/used.sh first."))
        (path / "scripts").mkdir()
        (path / "scripts" / "used.sh").write_text("#!/bin/sh\n")
        (path / "scripts" / "orphan.sh").write_text("#!/bin/sh\n")

        report = await lint_location(skills_root, SkillLocation("alpha", path))

        assert [f.code for f in report.findings] == ["unreferenced-resource"]
        assert "scripts/orphan.sh" in report.findings[0].message

    async def test_malformed_skill_is_an_error_rather_than_a_guess(self, write_skill, skills_root):
        path = write_skill("alpha", "no frontmatter")

        report = await lint_location(skills_root, SkillLocation("alpha", path))

        assert [f.severity for f in report.findings] == ["error"]

    async def test_unreadable_skill_file(self, skills_root):
        path = skills_root / "alpha"
        (path / "SKILL.md").mkdir(parents=True)

        report = await lint_location(skills_root, SkillLocation("alpha", path))

        assert [f.code for f in report.findings] == ["unreadable"]


class TestUnreferencedResources:
    async def test_provider_that_cannot_enumerate_is_not_second_guessed(self):
        skill = Skill("alpha", _BareProvider())

        assert await _unreferenced_resources(skill, "body") == []


class TestLintLocations:
    async def test_lints_every_skill(self, write_skill, skills_root):
        alpha = write_skill("alpha", _skill_md(version=None, body="Body."))
        beta = write_skill("beta", _skill_md(body="Body.").replace("alpha", "beta"))

        reports = await lint_locations(
            skills_root,
            [SkillLocation("alpha", alpha), SkillLocation("beta", beta)],
        )

        assert [len(r.findings) for r in reports] == [1, 0]
