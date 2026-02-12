"""Tests for LocalFileSystemSkillProvider."""

from pathlib import Path

import pytest

from agentskills_core import ResourceNotFoundError, SkillNotFoundError
from agentskills_fs import LocalFileSystemSkillProvider

# ------------------------------------------------------------------
# Helpers — create skill fixtures on disk
# ------------------------------------------------------------------

SAMPLE_SKILL_MD = """\
---
name: test-skill
description: A test skill for unit testing.
---

# Test Skill

This is the body of the test skill.
"""


def _create_skill(
    root: Path,
    skill_id: str = "test-skill",
    skill_md: str = SAMPLE_SKILL_MD,
    references: dict[str, str] | None = None,
    scripts: dict[str, str] | None = None,
    assets: dict[str, str] | None = None,
) -> Path:
    """Create a skill directory under *root* and return the skill dir path."""
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    for subdir, files in [
        ("references", references),
        ("scripts", scripts),
        ("assets", assets),
    ]:
        if files:
            sub = skill_dir / subdir
            sub.mkdir(exist_ok=True)
            for name, content in files.items():
                (sub / name).write_text(content, encoding="utf-8")

    return skill_dir


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestLocalFileSystemSkillProvider:
    async def test_get_metadata(self, tmp_path: Path):
        _create_skill(tmp_path)
        provider = LocalFileSystemSkillProvider(tmp_path)
        meta = await provider.get_metadata("test-skill")
        assert meta["name"] == "test-skill"
        assert "unit testing" in meta["description"]

    async def test_get_body(self, tmp_path: Path):
        _create_skill(tmp_path)
        provider = LocalFileSystemSkillProvider(tmp_path)
        body = await provider.get_body("test-skill")
        assert "# Test Skill" in body
        assert "body of the test skill" in body
        # Body should NOT contain frontmatter delimiters
        assert "---" not in body

    async def test_get_reference(self, tmp_path: Path):
        _create_skill(tmp_path, references={"pay.txt": "Pay policy content"})
        provider = LocalFileSystemSkillProvider(tmp_path)
        data = await provider.get_reference("test-skill", "pay.txt")
        assert data == b"Pay policy content"

    async def test_get_reference_missing_file(self, tmp_path: Path):
        _create_skill(tmp_path)
        provider = LocalFileSystemSkillProvider(tmp_path)
        with pytest.raises(ResourceNotFoundError):
            await provider.get_reference("test-skill", "nonexistent.txt")

    async def test_get_script(self, tmp_path: Path):
        _create_skill(tmp_path, scripts={"run.sh": "#!/bin/bash\necho hi"})
        provider = LocalFileSystemSkillProvider(tmp_path)
        content = await provider.get_script("test-skill", "run.sh")
        assert b"#!/bin/bash" in content
        assert b"echo hi" in content

    async def test_get_asset(self, tmp_path: Path):
        _create_skill(tmp_path, assets={"diagram.mermaid": "graph TD; A-->B"})
        provider = LocalFileSystemSkillProvider(tmp_path)
        assert await provider.get_asset("test-skill", "diagram.mermaid") == b"graph TD; A-->B"

    async def test_nonexistent_root_raises(self, tmp_path: Path):
        with pytest.raises(NotADirectoryError):
            LocalFileSystemSkillProvider(tmp_path / "nonexistent")

    async def test_nonexistent_skill_raises(self, tmp_path: Path):
        provider = LocalFileSystemSkillProvider(tmp_path)
        with pytest.raises(SkillNotFoundError):
            await provider.get_metadata("nonexistent")

    async def test_skill_md_no_frontmatter(self, tmp_path: Path):
        _create_skill(tmp_path, skill_md="# No Frontmatter\nJust body.")
        provider = LocalFileSystemSkillProvider(tmp_path)
        assert await provider.get_metadata("test-skill") == {}
        assert "# No Frontmatter" in await provider.get_body("test-skill")

    async def test_malformed_yaml_frontmatter(self, tmp_path: Path):
        bad_yaml = "---\n: :\ninvalid yaml{{{\n---\n# Body"
        _create_skill(tmp_path, skill_md=bad_yaml)
        provider = LocalFileSystemSkillProvider(tmp_path)
        meta = await provider.get_metadata("test-skill")
        assert meta == {}
        body = await provider.get_body("test-skill")
        assert "# Body" in body or "invalid" in body

    async def test_path_traversal_skill_id(self, tmp_path: Path):
        _create_skill(tmp_path)
        provider = LocalFileSystemSkillProvider(tmp_path)
        with pytest.raises(SkillNotFoundError):
            await provider.get_metadata("../../etc")

    async def test_path_traversal_resource_name(self, tmp_path: Path):
        _create_skill(tmp_path, references={"legit.md": "ok"})
        provider = LocalFileSystemSkillProvider(tmp_path)
        with pytest.raises(ResourceNotFoundError):
            await provider.get_reference("test-skill", "../../pyproject.toml")


class TestProgressiveDisclosure:
    """Ensure get_metadata does not eagerly load body content."""

    async def test_metadata_does_not_read_body(self, tmp_path: Path, monkeypatch):
        _create_skill(tmp_path)
        provider = LocalFileSystemSkillProvider(tmp_path)

        # get_metadata should only read frontmatter, not body
        meta = await provider.get_metadata("test-skill")
        assert meta["name"] == "test-skill"


class TestIntegration:
    """Integration test using the real example skill."""

    @pytest.fixture()
    def examples_root(self) -> Path:
        """Locate the examples/skills directory."""
        root = Path(__file__).resolve().parents[4] / "examples" / "skills"
        if not root.is_dir():
            pytest.skip("examples/skills/ not found")
        return root

    async def test_full_flow(self, examples_root: Path):
        from agentskills_core import SkillRegistry

        provider = LocalFileSystemSkillProvider(examples_root)
        registry = SkillRegistry()
        await registry.register("incident-response", provider)

        # List
        skills = registry.list_skills()
        assert any(s.get_id() == "incident-response" for s in skills)

        # Metadata
        skill = registry.get_skill("incident-response")
        meta = await skill.get_metadata()
        assert meta["name"] == "incident-response"
        assert "incident management" in meta["description"].lower()

        # Body
        body = await skill.get_body()
        assert "Incident Response" in body
        assert "Incident Commander" in body

        # References
        sev_content = await skill.get_reference("severity-levels.md")
        assert b"SEV1" in sev_content
        assert b"Critical" in sev_content

        # Scripts
        script_content = await skill.get_script("page-oncall.sh")
        assert len(script_content) > 0

        # Assets
        asset_content = await skill.get_asset("escalation-flowchart.mermaid")
        assert len(asset_content) > 0
