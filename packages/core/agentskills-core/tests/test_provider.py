"""Tests for SkillProvider ABC."""

import pytest

from agentskills_core import SkillProvider


class TestSkillProviderABC:
    """SkillProvider cannot be instantiated directly."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            SkillProvider()  # type: ignore[abstract]

    def test_concrete_subclass_works(self):
        """A fully-implemented subclass can be instantiated."""

        class StubProvider(SkillProvider):
            async def get_metadata(self, skill_id: str) -> dict:
                return {"name": skill_id, "description": "A test skill."}

            async def get_body(self, skill_id: str) -> str:
                return "# Test"

            async def get_script(self, skill_id: str, name: str) -> bytes:
                return b""

            async def get_asset(self, skill_id: str, name: str) -> bytes:
                return b""

            async def get_reference(self, skill_id: str, name: str) -> bytes:
                return b""

        provider = StubProvider()
        # Verify the instance was created — async methods are tested elsewhere
        assert provider is not None

    def test_partial_implementation_raises(self):
        """A subclass missing abstract methods cannot be instantiated."""

        class PartialProvider(SkillProvider):
            async def get_metadata(self, skill_id: str) -> dict:
                return {}

        with pytest.raises(TypeError):
            PartialProvider()  # type: ignore[abstract]
