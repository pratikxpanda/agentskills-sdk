"""Tests for the fixtures the package registers as a pytest plugin.

Nothing here imports the fixtures — the point is that installing the
package makes them available.
"""

from __future__ import annotations

from agentskills_core import SkillRegistry
from agentskills_testing import DEFAULT_SKILL_ID, InMemorySkill, InMemorySkillProvider


def test_sample_skill_has_one_resource_of_each_kind(sample_skill: InMemorySkill):
    assert isinstance(sample_skill, InMemorySkill)
    assert len(sample_skill.references) == 1
    assert len(sample_skill.scripts) == 1
    assert len(sample_skill.assets) == 1
    assert sample_skill.metadata["version"] == "1.0.0"


async def test_skill_provider_serves_the_sample_skill(skill_provider: InMemorySkillProvider):
    assert skill_provider.skill_ids() == [DEFAULT_SKILL_ID]
    assert (await skill_provider.get_metadata(DEFAULT_SKILL_ID))["name"] == DEFAULT_SKILL_ID


async def test_skill_registry_is_already_populated(skill_registry: SkillRegistry):
    assert [skill.get_id() for skill in skill_registry.list_skills()] == [DEFAULT_SKILL_ID]


async def test_skill_registry_renders_a_catalog(skill_registry: SkillRegistry):
    catalog = await skill_registry.get_skills_catalog()

    assert DEFAULT_SKILL_ID in catalog
