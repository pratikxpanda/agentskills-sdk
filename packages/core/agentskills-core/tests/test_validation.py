"""Tests for validation aligned with Agent Skills specification."""

from unittest.mock import AsyncMock

from agentskills_core import Skill, SkillNotFoundError, SkillProvider, validate_skill


def _skill(
    skill_id: str = "my-skill",
    body: str = "# Instructions",
    metadata: dict | None = None,
) -> Skill:
    provider = AsyncMock(spec=SkillProvider)
    provider.get_body.return_value = body
    provider.get_metadata.return_value = (
        metadata
        if metadata is not None
        else {"name": "my-skill", "description": "Does useful things."}
    )
    return Skill(skill_id=skill_id, provider=provider)


class TestValidateSkill:
    async def test_valid_skill(self):
        errors = await validate_skill(_skill())
        assert errors == []

    async def test_empty_body(self):
        errors = await validate_skill(_skill(body=""))
        assert any("body is empty" in e for e in errors)

    async def test_whitespace_only_body(self):
        errors = await validate_skill(_skill(body="   \n  "))
        assert any("body is empty" in e for e in errors)

    async def test_missing_name_in_metadata(self):
        errors = await validate_skill(_skill(metadata={"description": "Has a desc."}))
        assert any("missing required 'name'" in e for e in errors)

    async def test_missing_description_in_metadata(self):
        errors = await validate_skill(_skill(metadata={"name": "my-skill"}))
        assert any("missing required 'description'" in e for e in errors)

    async def test_name_mismatch(self):
        errors = await validate_skill(
            _skill(metadata={"name": "other-skill", "description": "Desc."}),
        )
        assert any("does not match" in e for e in errors)

    async def test_name_uppercase_rejected(self):
        errors = await validate_skill(
            _skill(
                skill_id="My-Skill",
                metadata={"name": "My-Skill", "description": "Desc."},
            ),
        )
        assert any("lowercase alphanumeric" in e for e in errors)

    async def test_name_consecutive_hyphens_rejected(self):
        errors = await validate_skill(
            _skill(
                skill_id="my--skill",
                metadata={"name": "my--skill", "description": "Desc."},
            ),
        )
        assert any("consecutive hyphens" in e for e in errors)

    async def test_name_starts_with_hyphen_rejected(self):
        errors = await validate_skill(
            _skill(
                skill_id="-my-skill",
                metadata={"name": "-my-skill", "description": "Desc."},
            ),
        )
        assert any("lowercase alphanumeric" in e for e in errors)

    async def test_name_ends_with_hyphen_rejected(self):
        errors = await validate_skill(
            _skill(
                skill_id="my-skill-",
                metadata={"name": "my-skill-", "description": "Desc."},
            ),
        )
        assert any("lowercase alphanumeric" in e for e in errors)

    async def test_name_too_long(self):
        long_name = "a" * 65
        errors = await validate_skill(
            _skill(
                skill_id=long_name,
                metadata={"name": long_name, "description": "Desc."},
            ),
        )
        assert any("exceeds 64 characters" in e for e in errors)

    async def test_description_too_long(self):
        long_desc = "x" * 1025
        errors = await validate_skill(
            _skill(metadata={"name": "my-skill", "description": long_desc}),
        )
        assert any("exceeds 1024 characters" in e for e in errors)

    async def test_body_exception(self):
        p = AsyncMock(spec=SkillProvider)
        p.get_body.side_effect = SkillNotFoundError("SKILL.md not found")
        p.get_metadata.return_value = {
            "name": "my-skill",
            "description": "Desc.",
        }
        errors = await validate_skill(Skill(skill_id="my-skill", provider=p))
        assert any("failed to read body" in e for e in errors)

    async def test_metadata_exception(self):
        p = AsyncMock(spec=SkillProvider)
        p.get_body.return_value = "# Body"
        p.get_metadata.side_effect = SkillNotFoundError("no metadata")
        errors = await validate_skill(Skill(skill_id="my-skill", provider=p))
        assert any("failed to read metadata" in e for e in errors)

    async def test_multiple_errors(self):
        errors = await validate_skill(
            _skill(body="", metadata={"name": "other"}),
        )
        # body empty + name mismatch + missing description = at least 3
        assert len(errors) >= 3
