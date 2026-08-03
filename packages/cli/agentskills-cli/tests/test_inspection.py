"""Tests for ``agentskills inspect``."""

from __future__ import annotations

import io

import pytest

from agentskills_cli.discovery import CliError, SkillLocation
from agentskills_cli.inspection import inspect_location, render_inspection_text


class TestInspectLocation:
    async def test_reports_what_the_agent_would_receive(self, write_skill, skills_root):
        path = write_skill("alpha")

        inspection = await inspect_location(skills_root, SkillLocation("alpha", path))

        assert inspection["id"] == "alpha"
        assert inspection["metadata"]["name"] == "alpha"
        assert "<name>alpha</name>" in inspection["catalogEntry"]
        assert inspection["body"].startswith("# Test")
        assert inspection["estimatedTokens"]["body"] > 0

    async def test_lists_resources(self, write_skill, skills_root):
        path = write_skill("alpha")
        (path / "references").mkdir()
        (path / "references" / "runbook.md").write_text("...")

        inspection = await inspect_location(skills_root, SkillLocation("alpha", path))

        assert inspection["resources"]["references"] == ["runbook.md"]

    async def test_invalid_skill_cannot_be_inspected(self, write_skill, skills_root):
        path = write_skill("alpha", "---\nname: alpha\n---\n\nbody")

        with pytest.raises(CliError, match="does not validate"):
            await inspect_location(skills_root, SkillLocation("alpha", path))


class TestRenderInspectionText:
    async def test_renders_every_section(self, write_skill, skills_root):
        path = write_skill("alpha")
        inspection = await inspect_location(skills_root, SkillLocation("alpha", path))
        out = io.StringIO()

        render_inspection_text(inspection, out)

        text = out.getvalue()
        assert "metadata" in text
        assert "resources\n  none" in text
        assert "catalog entry" in text
        assert "body" in text

    async def test_lists_resource_paths(self, write_skill, skills_root):
        path = write_skill("alpha")
        (path / "scripts").mkdir()
        (path / "scripts" / "run.sh").write_text("...")
        inspection = await inspect_location(skills_root, SkillLocation("alpha", path))
        out = io.StringIO()

        render_inspection_text(inspection, out)

        assert "scripts/run.sh" in out.getvalue()
