"""Tests for ``agentskills validate``."""

from __future__ import annotations

import yaml

from agentskills_tools.discovery import SkillLocation
from agentskills_tools.validate import (
    _yaml_detail,
    check_frontmatter,
    validate_location,
    validate_locations,
)


class TestCheckFrontmatter:
    def test_valid_frontmatter_has_no_findings(self):
        assert check_frontmatter("---\nname: a\n---\n\nbody") == []

    def test_empty_frontmatter_is_not_a_structural_problem(self):
        # An empty mapping is well-formed; the spec checks catch it.
        assert check_frontmatter("---\n---\n\nbody") == []

    def test_missing_delimiter(self):
        [finding] = check_frontmatter("# Just a heading\n")

        assert finding.code == "frontmatter-missing"
        assert finding.line == 1

    def test_unclosed_block(self):
        [finding] = check_frontmatter("---\nname: a\n")

        assert finding.code == "frontmatter-unclosed"

    def test_oversized_block_is_reported_rather_than_silently_ignored(self):
        padding = "x" * (256 * 1024)
        [finding] = check_frontmatter(f"---\nname: {padding}\n---\n\nbody")

        assert finding.code == "frontmatter-too-large"

    def test_invalid_yaml_reports_the_line(self):
        [finding] = check_frontmatter("---\nname: a\n  description: b: c\n---\n\nbody")

        assert finding.code == "frontmatter-invalid-yaml"
        assert finding.line == 3

    def test_sequence_instead_of_mapping(self):
        [finding] = check_frontmatter("---\n- name\n- description\n---\n\nbody")

        assert finding.code == "frontmatter-not-a-mapping"
        assert "not list" in finding.message


class TestYamlDetail:
    def test_falls_back_to_the_message_when_there_is_no_mark(self):
        reason, line = _yaml_detail(yaml.YAMLError("something went wrong"))

        assert reason == "something went wrong"
        assert line is None


class TestValidateLocation:
    async def test_valid_skill_reports_nothing(self, write_skill, skills_root):
        path = write_skill("alpha")

        report = await validate_location(skills_root, SkillLocation("alpha", path))

        assert report.findings == []
        assert report.ok

    async def test_spec_errors_are_reported_without_the_redundant_prefix(
        self, write_skill, skills_root
    ):
        path = write_skill("alpha", "---\nname: not-alpha\ndescription: d\n---\n\nbody")

        report = await validate_location(skills_root, SkillLocation("alpha", path))

        assert [f.code for f in report.findings] == ["spec"]
        assert report.findings[0].message.startswith("metadata name")

    async def test_frontmatter_failure_suppresses_the_spec_checks(self, write_skill, skills_root):
        path = write_skill("alpha", "no frontmatter here")

        report = await validate_location(skills_root, SkillLocation("alpha", path))

        assert [f.code for f in report.findings] == ["frontmatter-missing"]

    async def test_unreadable_skill_file(self, skills_root):
        path = skills_root / "alpha"
        (path / "SKILL.md").mkdir(parents=True)

        report = await validate_location(skills_root, SkillLocation("alpha", path))

        assert [f.code for f in report.findings] == ["unreadable"]


class TestEvalFiles:
    async def test_a_good_eval_file_is_silent(self, write_skill, write_eval, skills_root):
        path = write_skill("alpha")
        write_eval("alpha", "cases:\n  - prompt: a\n    expect:\n      - contains: a\n")

        report = await validate_location(skills_root, SkillLocation("alpha", path))

        assert report.findings == []

    async def test_a_broken_eval_file_fails_the_skill(self, write_skill, write_eval, skills_root):
        path = write_skill("alpha")
        write_eval("alpha", "cases: []\n")

        report = await validate_location(skills_root, SkillLocation("alpha", path))

        assert [f.code for f in report.findings] == ["eval-no-cases"]
        assert not report.ok

    async def test_eval_files_are_checked_even_when_the_frontmatter_is_broken(
        self, write_skill, write_eval, skills_root
    ):
        # The two documents are independent; suppressing one because the
        # other is damaged would only cost the author a second round trip.
        path = write_skill("alpha", "no frontmatter here")
        write_eval("alpha", "cases: []\n")

        report = await validate_location(skills_root, SkillLocation("alpha", path))

        assert [f.code for f in report.findings] == ["frontmatter-missing", "eval-no-cases"]


class TestValidateLocations:
    async def test_reports_every_skill(self, write_skill, skills_root):
        alpha = write_skill("alpha")
        beta = write_skill("beta", "broken")

        reports = await validate_locations(
            skills_root,
            [SkillLocation("alpha", alpha), SkillLocation("beta", beta)],
        )

        assert [r.ok for r in reports] == [True, False]
