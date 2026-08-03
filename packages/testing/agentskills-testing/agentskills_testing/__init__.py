"""Conformance suite and test doubles for Agent Skills providers.

Two things live here:

* :class:`ProviderConformanceSuite` — subclass it, supply a ``provider``
  fixture, and pytest runs the whole provider contract against your
  implementation.
* :class:`InMemorySkillProvider` — a real, spec-compliant provider
  backed by a dict, for tests that need a skill but not a disk.

See https://github.com/pratikxpanda/agentskills-sdk for the guide.
"""

from agentskills_testing.conformance import (
    ASSET_BYTES,
    ASSET_NAME,
    CONTRACT,
    MISSING_ID,
    MISSING_RESOURCE,
    REFERENCE_BYTES,
    REFERENCE_NAME,
    SCRIPT_BYTES,
    SCRIPT_NAME,
    SKILL_ID,
    TRAVERSAL_IDENTIFIERS,
    ContentLimitConformanceSuite,
    ProviderConformanceSuite,
)
from agentskills_testing.memory import (
    DEFAULT_BODY,
    DEFAULT_DESCRIPTION,
    DEFAULT_SKILL_ID,
    InMemorySkill,
    InMemorySkillProvider,
    build_skill,
    render_skill_md,
)

__all__ = [
    "ASSET_BYTES",
    "ASSET_NAME",
    "CONTRACT",
    "DEFAULT_BODY",
    "DEFAULT_DESCRIPTION",
    "DEFAULT_SKILL_ID",
    "MISSING_ID",
    "MISSING_RESOURCE",
    "REFERENCE_BYTES",
    "REFERENCE_NAME",
    "SCRIPT_BYTES",
    "SCRIPT_NAME",
    "SKILL_ID",
    "TRAVERSAL_IDENTIFIERS",
    "ContentLimitConformanceSuite",
    "InMemorySkill",
    "InMemorySkillProvider",
    "ProviderConformanceSuite",
    "build_skill",
    "render_skill_md",
]
