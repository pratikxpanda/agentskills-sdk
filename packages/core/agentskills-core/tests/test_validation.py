"""Tests for validation aligned with Agent Skills specification."""

import logging
from datetime import date
from unittest.mock import AsyncMock

import pytest

from agentskills_core import (
    Skill,
    SkillNotFoundError,
    SkillProvider,
    SkillRegistry,
    validate_skill,
    validate_version,
)


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


class TestOptionalFieldValidation:
    """Tests for optional metadata field type validation."""

    async def test_valid_optional_fields(self):
        errors = await validate_skill(
            _skill(
                metadata={
                    "name": "my-skill",
                    "description": "Desc.",
                    "license": "MIT",
                    "compatibility": {"ide": ["vscode"]},
                    "metadata": {"author": "test"},
                    "allowed-tools": ["read_file"],
                },
            ),
        )
        assert errors == []

    async def test_license_wrong_type(self):
        errors = await validate_skill(
            _skill(
                metadata={
                    "name": "my-skill",
                    "description": "Desc.",
                    "license": 123,
                },
            ),
        )
        assert any("'license' must be str" in e for e in errors)

    async def test_compatibility_wrong_type(self):
        errors = await validate_skill(
            _skill(
                metadata={
                    "name": "my-skill",
                    "description": "Desc.",
                    "compatibility": "vscode",
                },
            ),
        )
        assert any("'compatibility' must be dict" in e for e in errors)

    async def test_allowed_tools_wrong_type(self):
        errors = await validate_skill(
            _skill(
                metadata={
                    "name": "my-skill",
                    "description": "Desc.",
                    "allowed-tools": "read_file",
                },
            ),
        )
        assert any("'allowed-tools' must be list" in e for e in errors)

    async def test_unknown_keys_logged(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            errors = await validate_skill(
                _skill(
                    metadata={
                        "name": "my-skill",
                        "description": "Desc.",
                        "custom-field": "value",
                    },
                ),
            )
        # Unknown keys are warnings, not errors
        assert errors == []
        assert "unknown metadata keys" in caplog.text
        assert "custom-field" in caplog.text


class TestSelectionMetadataValidation:
    """``when_to_use`` / ``when_not_to_use`` are optional bounded lists."""

    @staticmethod
    async def _errors(**fields: object) -> list[str]:
        return await validate_skill(
            _skill(metadata={"name": "my-skill", "description": "Desc.", **fields}),
        )

    async def test_valid_lists(self):
        assert (
            await self._errors(
                when_to_use=["A production service is down"],
                when_not_to_use=["Debugging a failing test locally"],
            )
            == []
        )

    async def test_absent_is_valid(self):
        assert await self._errors() == []

    async def test_empty_list_is_valid(self):
        assert await self._errors(when_to_use=[], when_not_to_use=[]) == []

    @pytest.mark.parametrize("key", ["when_to_use", "when_not_to_use"])
    async def test_wrong_type(self, key):
        errors = await self._errors(**{key: "a string"})
        assert any(f"'{key}' must be list" in e for e in errors)

    @pytest.mark.parametrize("key", ["when_to_use", "when_not_to_use"])
    async def test_non_string_entry(self, key):
        errors = await self._errors(**{key: ["fine", 7]})
        assert any(f"'{key}' entry 1 must be str, got int" in e for e in errors)

    async def test_blank_entry(self):
        errors = await self._errors(when_to_use=["   "])
        assert any("entry 0 is empty" in e for e in errors)

    async def test_entry_over_length_limit(self):
        errors = await self._errors(when_to_use=["x" * 201])
        assert any("201 characters, over the limit of 200" in e for e in errors)

    async def test_entry_at_length_limit(self):
        assert await self._errors(when_to_use=["x" * 200]) == []

    async def test_too_many_entries(self):
        errors = await self._errors(when_to_use=[f"case {n}" for n in range(6)])
        assert any("6 entries, over the limit of 5" in e for e in errors)

    async def test_five_entries_allowed(self):
        assert await self._errors(when_to_use=[f"case {n}" for n in range(5)]) == []

    async def test_not_reported_as_unknown_keys(self, caplog):
        with caplog.at_level(logging.WARNING):
            await self._errors(when_to_use=["A case"])
        assert "unknown metadata keys" not in caplog.text


class TestBoundaryValidation:
    """Tests for boundary-length names and descriptions."""

    async def test_metadata_wrong_type(self):
        """metadata field with wrong type (str instead of dict) is rejected."""
        errors = await validate_skill(
            _skill(
                metadata={
                    "name": "my-skill",
                    "description": "Desc.",
                    "metadata": "should-be-a-dict",
                },
            ),
        )
        assert any("'metadata' must be dict" in e for e in errors)

    async def test_name_exactly_64_chars(self):
        """Name at exactly 64 characters (boundary) should pass."""
        name = "a" * 64
        errors = await validate_skill(
            _skill(
                skill_id=name,
                metadata={"name": name, "description": "Desc."},
            ),
        )
        assert errors == []

    async def test_description_exactly_1024_chars(self):
        """Description at exactly 1024 characters (boundary) should pass."""
        desc = "x" * 1024
        errors = await validate_skill(
            _skill(metadata={"name": "my-skill", "description": desc}),
        )
        assert errors == []

    async def test_single_char_name(self):
        """Single-character valid name should pass."""
        errors = await validate_skill(
            _skill(
                skill_id="a",
                metadata={"name": "a", "description": "Desc."},
            ),
        )
        assert errors == []


class TestVersionValidation:
    """Tests for the optional, non-spec ``version`` frontmatter field."""

    async def test_absent_version_is_valid(self):
        errors = await validate_skill(
            _skill(metadata={"name": "my-skill", "description": "Desc."}),
        )
        assert errors == []

    @pytest.mark.parametrize(
        "version",
        [
            "0.0.0",
            "1.0.0",
            "10.20.30",
            "1.0.0-alpha",
            "2.1.0-rc.1",
            "1.0.0-0.3.7",
            "1.0.0+build.5",
            "1.0.0-beta.1+exp.sha.5114f85",
        ],
    )
    async def test_valid_semver_accepted(self, version):
        errors = await validate_skill(
            _skill(
                metadata={
                    "name": "my-skill",
                    "description": "Desc.",
                    "version": version,
                },
            ),
        )
        assert errors == []

    @pytest.mark.parametrize(
        "version",
        ["1", "1.0", "v1.0.0", "1.0.0.0", "01.0.0", "1.0.0-", "", "latest"],
    )
    async def test_invalid_semver_rejected(self, version):
        errors = await validate_skill(
            _skill(
                metadata={
                    "name": "my-skill",
                    "description": "Desc.",
                    "version": version,
                },
            ),
        )
        assert any("is not valid semver" in e for e in errors)

    @pytest.mark.parametrize(
        "version",
        [1, 1.0, date(2024, 1, 15), ["1.0.0"], None],
    )
    async def test_non_string_version_names_the_yaml_trap(self, version):
        """YAML coerces unquoted versions; the error must say so."""
        errors = await validate_skill(
            _skill(
                metadata={
                    "name": "my-skill",
                    "description": "Desc.",
                    "version": version,
                },
            ),
        )
        assert any("must be a quoted string" in e for e in errors)
        assert any('version: "1.0.0"' in e for e in errors)

    async def test_version_is_a_known_key(self, caplog):
        """``version`` must not trigger the unknown-key warning."""
        with caplog.at_level(logging.WARNING):
            await validate_skill(
                _skill(
                    metadata={
                        "name": "my-skill",
                        "description": "Desc.",
                        "version": "1.0.0",
                    },
                ),
            )
        assert "unknown metadata keys" not in caplog.text

    async def test_error_message_includes_skill_id(self):
        errors = await validate_skill(
            _skill(
                metadata={
                    "name": "my-skill",
                    "description": "Desc.",
                    "version": "nope",
                },
            ),
        )
        assert any(e.startswith("Skill 'my-skill':") for e in errors)

    async def test_invalid_version_fails_registration(self):
        """Registration is the enforcement point, not just validate_skill()."""
        provider = AsyncMock(spec=SkillProvider)
        provider.get_body.return_value = "# Instructions"
        provider.get_metadata.return_value = {
            "name": "my-skill",
            "description": "Desc.",
            "version": "1.0",
        }
        registry = SkillRegistry()
        with pytest.raises(ValueError, match="is not valid semver"):
            await registry.register("my-skill", provider)
        assert registry.list_skills() == []

    async def test_valid_version_registers(self):
        provider = AsyncMock(spec=SkillProvider)
        provider.get_body.return_value = "# Instructions"
        provider.get_metadata.return_value = {
            "name": "my-skill",
            "description": "Desc.",
            "version": "1.0.0",
        }
        registry = SkillRegistry()
        await registry.register("my-skill", provider)
        assert len(registry.list_skills()) == 1


class TestValidateVersion:
    """Direct tests for the exported helper."""

    def test_valid_returns_none(self):
        assert validate_version("1.2.3") is None

    def test_invalid_returns_message(self):
        message = validate_version("1.2")
        assert message is not None
        assert "is not valid semver" in message

    def test_float_message_shows_repr(self):
        message = validate_version(1.0)
        assert message is not None
        assert "got float" in message
