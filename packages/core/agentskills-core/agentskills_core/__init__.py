"""Core runtime model for the Agent Skills format.

This package provides the foundational abstractions for registering,
validating, and accessing `Agent Skills <https://agentskills.io>`_:

* :class:`SkillProvider` -- abstract base class for skill backends.
* :class:`Skill` -- lightweight runtime handle to a single skill.
* :class:`SkillRegistry` -- unified index with explicit registration
  and built-in catalog builder.
* :func:`validate_skill` -- validates a skill against the specification.
* :func:`validate_version` -- validates an optional semver ``version`` field.
* :func:`encode_resource_content` -- safely encodes resource bytes as tool output.
* :class:`SkillNotFoundError` -- raised when a skill does not exist.
* :class:`ResourceNotFoundError` -- raised when a resource within a skill
  does not exist.
* :class:`ResourceListingNotSupportedError` -- raised when a provider cannot
  enumerate a skill's resources.
* :class:`SkillUnavailableError` -- raised when a backend is unreachable or
  fails transiently, as distinct from a skill that does not exist.
* :class:`AgentSkillsError` -- base class for all library exceptions.

Install::

    pip install agentskills-core
"""

from agentskills_core.encoding import (
    DEFAULT_MAX_INLINE_BINARY_BYTES,
    encode_resource_content,
)
from agentskills_core.exceptions import (
    AgentSkillsError,
    ResourceListingNotSupportedError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillUnavailableError,
)
from agentskills_core.parsing import split_frontmatter
from agentskills_core.provider import RESOURCE_KINDS, SkillProvider
from agentskills_core.registry import SkillRegistry
from agentskills_core.skill import Skill
from agentskills_core.validation import validate_skill, validate_version

__all__ = [
    "DEFAULT_MAX_INLINE_BINARY_BYTES",
    "RESOURCE_KINDS",
    "AgentSkillsError",
    "ResourceListingNotSupportedError",
    "ResourceNotFoundError",
    "Skill",
    "SkillNotFoundError",
    "SkillProvider",
    "SkillRegistry",
    "SkillUnavailableError",
    "encode_resource_content",
    "split_frontmatter",
    "validate_skill",
    "validate_version",
]
