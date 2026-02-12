"""Core runtime model for the Agent Skills format.

This package provides the foundational abstractions for registering,
validating, and accessing `Agent Skills <https://agentskills.io>`_:

* :class:`SkillProvider` -- abstract base class for skill backends.
* :class:`Skill` -- lightweight runtime handle to a single skill.
* :class:`SkillRegistry` -- unified index with explicit registration
  and built-in catalog builder.
* :func:`validate_skill` -- validates a skill against the specification.
* :class:`SkillNotFoundError` -- raised when a skill does not exist.
* :class:`ResourceNotFoundError` -- raised when a resource within a skill
  does not exist.
* :class:`AgentSkillsError` -- base class for all library exceptions.

Install::

    pip install agentskills-core
"""

from agentskills_core.exceptions import (
    AgentSkillsError,
    ResourceNotFoundError,
    SkillNotFoundError,
)
from agentskills_core.parsing import split_frontmatter
from agentskills_core.provider import SkillProvider
from agentskills_core.registry import SkillRegistry
from agentskills_core.skill import Skill
from agentskills_core.validation import validate_skill

__all__ = [
    "AgentSkillsError",
    "ResourceNotFoundError",
    "Skill",
    "SkillNotFoundError",
    "SkillProvider",
    "SkillRegistry",
    "split_frontmatter",
    "validate_skill",
]
