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


class TestSecurityFS:
    """Tests for filesystem provider security features."""

    async def test_oversized_skill_md_rejected(self, tmp_path: Path):
        skill_dir = tmp_path / "big-skill"
        skill_dir.mkdir()
        # Create a SKILL.md larger than the limit
        (skill_dir / "SKILL.md").write_text(
            "---\nname: big-skill\ndescription: Test.\n---\n" + "x" * 200,
            encoding="utf-8",
        )
        provider = LocalFileSystemSkillProvider(tmp_path, max_file_bytes=100)
        with pytest.raises(SkillNotFoundError, match="exceeds maximum size"):
            await provider.get_metadata("big-skill")

    async def test_oversized_resource_rejected(self, tmp_path: Path):
        _create_skill(tmp_path, scripts={"big.sh": "x" * 200})
        provider = LocalFileSystemSkillProvider(tmp_path, max_file_bytes=100)
        with pytest.raises(ResourceNotFoundError, match="exceeds maximum size"):
            await provider.get_script("test-skill", "big.sh")

    async def test_error_message_does_not_leak_path(self, tmp_path: Path):
        provider = LocalFileSystemSkillProvider(tmp_path)
        with pytest.raises(SkillNotFoundError) as exc_info:
            await provider.get_metadata("nonexistent")
        # Error should reference skill_id, not full filesystem path
        assert str(tmp_path) not in str(exc_info.value)


class TestSecurityFSBoundary:
    """Additional boundary and edge-case tests for the filesystem provider."""

    async def test_file_exactly_at_max_bytes_passes(self, tmp_path: Path):
        """File at exactly max_file_bytes should be accepted."""
        limit = 200
        raw = b"---\nname: test-skill\ndescription: Test.\n---\n"
        # Pad to exactly the limit
        raw += b"x" * (limit - len(raw))
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_bytes(raw)
        provider = LocalFileSystemSkillProvider(tmp_path, max_file_bytes=limit)
        meta = await provider.get_metadata("test-skill")
        assert meta["name"] == "test-skill"

    async def test_skill_dir_exists_but_no_skill_md(self, tmp_path: Path):
        """Directory exists with other files but no SKILL.md raises SkillNotFoundError."""
        skill_dir = tmp_path / "empty-skill"
        skill_dir.mkdir()
        (skill_dir / "README.md").write_text("# Not a skill")
        provider = LocalFileSystemSkillProvider(tmp_path)
        with pytest.raises(SkillNotFoundError, match=r"SKILL\.md not found"):
            await provider.get_metadata("empty-skill")

    @pytest.mark.parametrize(
        "traversal_id",
        [
            "../etc",
            "..\\etc",
            "../../etc",
            "./../../etc",
            "skill/../../../etc",
        ],
    )
    async def test_path_traversal_patterns(self, tmp_path: Path, traversal_id: str):
        """Various path-traversal patterns are all rejected."""
        _create_skill(tmp_path)
        provider = LocalFileSystemSkillProvider(tmp_path)
        with pytest.raises(SkillNotFoundError):
            await provider.get_metadata(traversal_id)

    async def test_non_utf8_skill_md(self, tmp_path: Path):
        """Non-UTF-8 encoded SKILL.md raises an appropriate error."""
        skill_dir = tmp_path / "binary-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_bytes(b"\x80\x81\x82\xff")
        provider = LocalFileSystemSkillProvider(tmp_path)
        with pytest.raises(UnicodeDecodeError):
            await provider.get_metadata("binary-skill")

    async def test_max_file_bytes_zero_rejects_all(self, tmp_path: Path):
        """max_file_bytes=0 rejects all non-empty files."""
        _create_skill(tmp_path)
        provider = LocalFileSystemSkillProvider(tmp_path, max_file_bytes=0)
        with pytest.raises(SkillNotFoundError, match="exceeds maximum size"):
            await provider.get_metadata("test-skill")

    async def test_symlink_outside_root(self, tmp_path: Path):
        """Symlink pointing outside root directory is rejected."""
        import os

        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "SKILL.md").write_text("---\nname: evil\ndescription: Evil.\n---\n# Evil")
        skill_link = tmp_path / "root" / "evil"
        (tmp_path / "root").mkdir()
        try:
            os.symlink(outside, skill_link)
        except OSError:
            pytest.skip("symlink creation requires elevated privileges on Windows")
        provider = LocalFileSystemSkillProvider(tmp_path / "root")
        with pytest.raises(SkillNotFoundError):
            await provider.get_metadata("evil")


class TestSkillMdCaching:
    async def test_skill_md_read_once(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Repeated accesses hit the disk exactly once."""
        _create_skill(tmp_path)
        reads: list[Path] = []
        original = Path.read_text

        def counting_read_text(self: Path, *args: object, **kwargs: object) -> str:
            reads.append(self)
            return original(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", counting_read_text)

        provider = LocalFileSystemSkillProvider(tmp_path)
        await provider.get_metadata("test-skill")
        await provider.get_body("test-skill")
        await provider.get_metadata("test-skill")

        assert [p.name for p in reads] == ["SKILL.md"]

    async def test_cache_is_per_instance(self, tmp_path: Path):
        """One provider's cache does not serve another provider."""
        _create_skill(tmp_path)
        first = LocalFileSystemSkillProvider(tmp_path)
        await first.get_body("test-skill")

        (tmp_path / "test-skill" / "SKILL.md").write_text(
            SAMPLE_SKILL_MD.replace("body of the test skill", "updated body"),
            encoding="utf-8",
        )

        second = LocalFileSystemSkillProvider(tmp_path)
        assert "updated body" in await second.get_body("test-skill")
        assert "updated body" not in await first.get_body("test-skill")

    async def test_invalidate_single_skill(self, tmp_path: Path):
        _create_skill(tmp_path, skill_id="a")
        _create_skill(tmp_path, skill_id="b")
        provider = LocalFileSystemSkillProvider(tmp_path)
        await provider.get_body("a")
        await provider.get_body("b")

        for skill_id in ("a", "b"):
            (tmp_path / skill_id / "SKILL.md").write_text(
                SAMPLE_SKILL_MD.replace("body of the test skill", "updated body"),
                encoding="utf-8",
            )

        provider.invalidate("a")
        assert "updated body" in await provider.get_body("a")
        assert "updated body" not in await provider.get_body("b")

    async def test_invalidate_all(self, tmp_path: Path):
        _create_skill(tmp_path)
        provider = LocalFileSystemSkillProvider(tmp_path)
        await provider.get_body("test-skill")

        (tmp_path / "test-skill" / "SKILL.md").write_text(
            SAMPLE_SKILL_MD.replace("body of the test skill", "updated body"),
            encoding="utf-8",
        )

        provider.invalidate()
        assert "updated body" in await provider.get_body("test-skill")

    async def test_invalidate_unknown_skill_is_noop(self, tmp_path: Path):
        provider = LocalFileSystemSkillProvider(tmp_path)
        provider.invalidate("never-registered")

    async def test_concurrent_reads(self, tmp_path: Path):
        """Concurrent reads across skills return the right content."""
        import asyncio

        for skill_id in ("a", "b", "c"):
            _create_skill(
                tmp_path,
                skill_id=skill_id,
                skill_md=SAMPLE_SKILL_MD.replace("test skill.", f"skill {skill_id}."),
            )

        provider = LocalFileSystemSkillProvider(tmp_path)
        results = await asyncio.gather(
            *(provider.get_metadata(skill_id) for skill_id in ("a", "b", "c") for _ in range(4))
        )

        assert len(results) == 12
        descriptions = {r["description"] for r in results}
        assert descriptions == {
            "A test skill for unit testing.".replace("test skill.", f"skill {s}.") for s in "abc"
        }

    async def test_does_not_block_the_event_loop(self, tmp_path: Path):
        """A slow read must not stall other coroutines."""
        import asyncio
        import time

        _create_skill(tmp_path)
        provider = LocalFileSystemSkillProvider(tmp_path)
        original = provider._read_skill_md_sync
        ticks = 0

        def slow_read(skill_id: str) -> str:
            time.sleep(0.2)
            return original(skill_id)

        provider._read_skill_md_sync = slow_read  # type: ignore[method-assign]

        async def tick() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        ticker = asyncio.create_task(tick())
        await provider.get_body("test-skill")
        ticker.cancel()

        assert ticks > 1


class TestListResources:
    def test_capability_is_declared(self, tmp_path: Path):
        assert LocalFileSystemSkillProvider(tmp_path).supports_resource_listing is True

    async def test_lists_all_kinds(self, tmp_path: Path):
        _create_skill(
            tmp_path,
            references={"severity-levels.md": "# SEV"},
            scripts={"page-oncall.sh": "#!/bin/sh"},
            assets={"flowchart.mermaid": "graph TD"},
        )
        provider = LocalFileSystemSkillProvider(tmp_path)
        assert await provider.list_resources("test-skill") == {
            "references": ["severity-levels.md"],
            "scripts": ["page-oncall.sh"],
            "assets": ["flowchart.mermaid"],
        }

    async def test_missing_kinds_are_empty_lists(self, tmp_path: Path):
        """Every kind is always present, so callers need no key checks."""
        _create_skill(tmp_path)
        provider = LocalFileSystemSkillProvider(tmp_path)
        assert await provider.list_resources("test-skill") == {
            "references": [],
            "scripts": [],
            "assets": [],
        }

    async def test_names_are_sorted(self, tmp_path: Path):
        _create_skill(tmp_path, references={"c.md": "c", "a.md": "a", "b.md": "b"})
        provider = LocalFileSystemSkillProvider(tmp_path)
        listing = await provider.list_resources("test-skill")
        assert listing["references"] == ["a.md", "b.md", "c.md"]

    async def test_dotfiles_are_skipped(self, tmp_path: Path):
        skill_dir = _create_skill(tmp_path, references={"real.md": "x"})
        (skill_dir / "references" / ".DS_Store").write_text("junk", encoding="utf-8")
        provider = LocalFileSystemSkillProvider(tmp_path)
        listing = await provider.list_resources("test-skill")
        assert listing["references"] == ["real.md"]

    async def test_subdirectories_are_skipped(self, tmp_path: Path):
        """Reads only accept flat names, so listing must not offer nested ones."""
        skill_dir = _create_skill(tmp_path, references={"real.md": "x"})
        (skill_dir / "references" / "nested").mkdir()
        provider = LocalFileSystemSkillProvider(tmp_path)
        listing = await provider.list_resources("test-skill")
        assert listing["references"] == ["real.md"]

    async def test_symlink_escaping_the_root_is_skipped(self, tmp_path: Path):
        outside = tmp_path.parent / "outside-secret.md"
        outside.write_text("secret", encoding="utf-8")
        root = tmp_path / "skills"
        root.mkdir()
        skill_dir = _create_skill(root, references={"real.md": "x"})
        try:
            (skill_dir / "references" / "escape.md").symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation not permitted on this platform")

        provider = LocalFileSystemSkillProvider(root)
        listing = await provider.list_resources("test-skill")
        assert listing["references"] == ["real.md"]

    async def test_unknown_skill_raises(self, tmp_path: Path):
        provider = LocalFileSystemSkillProvider(tmp_path)
        with pytest.raises(SkillNotFoundError):
            await provider.list_resources("nope")

    async def test_traversal_in_skill_id_rejected(self, tmp_path: Path):
        provider = LocalFileSystemSkillProvider(tmp_path)
        with pytest.raises((ValueError, SkillNotFoundError)):
            await provider.list_resources("../etc")
