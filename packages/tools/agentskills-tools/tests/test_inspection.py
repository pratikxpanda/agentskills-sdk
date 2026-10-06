"""Tests for ``agentskills inspect``."""

from __future__ import annotations

import io
from hashlib import sha256

import pytest

from agentskills_tools.discovery import CliError, SkillLocation
from agentskills_tools.inspection import (
    inspect_location,
    inspect_native_location,
    render_inspection_text,
)


class TestInspectNativeLocation:
    async def test_reports_exact_manifest_without_legacy_body(self, write_skill, skills_root):
        path = write_skill("alpha")
        source = (
            b"\xef\xbb\xbf---\r\nname: alpha\r\ndescription: Native example\r\n"
            b"custom: {enabled: true}\r\n---\r\n\r\n# Original\r\n"
        )
        (path / "SKILL.md").write_bytes(source)
        (path / "data").mkdir()
        (path / "data" / "blob.bin").write_bytes(b"\x00\xff")
        (path / ".settings").write_bytes(b"hidden")

        inspection = await inspect_native_location(skills_root, SkillLocation("alpha", path))

        assert inspection["scope"] == "localSkillSnapshot"
        assert inspection["mode"] == "native"
        assert inspection["fileCount"] == 3
        assert inspection["totalBytes"] == len(source) + 8
        assert inspection["manifest"]["uri"] == "skill://alpha/SKILL.md"
        assert inspection["manifest"]["frontmatter"]["custom"] == {"enabled": True}
        entries = {entry["uri"]: entry for entry in inspection["manifest"]["resources"]}
        assert entries["skill://alpha/SKILL.md"]["digest"] == "sha256:" + sha256(source).hexdigest()
        assert entries["skill://alpha/SKILL.md"]["size"] == len(source)
        assert entries["skill://alpha/data/blob.bin"]["size"] == 2
        assert "skill://alpha/.settings" in entries
        assert "body" not in inspection
        assert "catalogEntry" not in inspection
        assert inspection["limits"]["maxFiles"] == 512
        assert inspection["protocolRequirements"]["directoryRead"] is False

    async def test_rejects_invalid_native_frontmatter(self, write_skill, skills_root):
        path = write_skill("alpha", "---\nname: alpha\n---\n\nbody")

        with pytest.raises(CliError, match=r"cannot inspect native skill 'alpha'.*description"):
            await inspect_native_location(skills_root, SkillLocation("alpha", path))

    async def test_enforces_provider_byte_limit(self, write_skill, skills_root):
        path = write_skill("alpha")

        with pytest.raises(CliError, match="cannot inspect native skill 'alpha'"):
            await inspect_native_location(
                skills_root, SkillLocation("alpha", path), max_file_bytes=1
            )


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
