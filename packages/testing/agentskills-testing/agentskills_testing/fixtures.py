"""Pytest fixtures, registered automatically as a plugin.

Installing ``agentskills-testing`` makes these available in any test
without an import or a ``conftest.py`` entry, via the ``pytest11``
entry point.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from agentskills_core import SkillRegistry
from agentskills_testing.memory import (
    DEFAULT_SKILL_ID,
    InMemorySkill,
    InMemorySkillProvider,
    build_skill,
)


@pytest.fixture
def sample_skill() -> InMemorySkill:
    """A single valid skill with one resource of each kind."""
    return build_skill(
        DEFAULT_SKILL_ID,
        version="1.0.0",
        references={"severity-levels.md": b"# Severity\n\nSEV1 is customer-visible.\n"},
        scripts={"page-oncall.sh": b"#!/bin/sh\necho paging\n"},
        assets={"flowchart.mermaid": b"graph TD; A-->B\n"},
    )


@pytest.fixture
def skill_provider(sample_skill: InMemorySkill) -> InMemorySkillProvider:
    """An :class:`InMemorySkillProvider` holding :func:`sample_skill`."""
    return InMemorySkillProvider({DEFAULT_SKILL_ID: sample_skill})


@pytest_asyncio.fixture
async def skill_registry(skill_provider: InMemorySkillProvider) -> SkillRegistry:
    """A registry with :func:`skill_provider`'s skill already registered."""
    registry = SkillRegistry()
    await registry.register(DEFAULT_SKILL_ID, skill_provider)
    return registry
