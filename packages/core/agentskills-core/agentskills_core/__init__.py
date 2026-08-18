"""Core runtime model for the Agent Skills format.

This package provides the foundational abstractions for registering,
validating, and accessing `Agent Skills <https://agentskills.io>`_:

* :class:`SkillProvider` -- abstract base class for skill backends.
* :class:`Skill` -- lightweight runtime handle to a single skill.
* :class:`SkillRegistry` -- unified index with explicit registration
  and built-in catalog builder.
* :func:`validate_skill` -- validates a skill against the specification.
* :func:`validate_version` -- validates an optional semver ``version`` field.
* :func:`get_logger` -- returns a logger in the shared ``agentskills.*`` namespace.
* :func:`redact_url` -- strips credentials from a URL before it is logged or raised.
* :func:`encode_resource_content` -- safely encodes resource bytes as tool output.
* :class:`SkillNotFoundError` -- raised when a skill does not exist.
* :class:`ResourceNotFoundError` -- raised when a resource within a skill
  does not exist.
* :class:`ResourceListingNotSupportedError` -- raised when a provider cannot
  enumerate a skill's resources.
* :class:`DiscoveryNotSupportedError` -- raised when a provider cannot
  enumerate the skills it holds.
* :class:`SkillUnavailableError` -- raised when a backend is unreachable or
  fails transiently, as distinct from a skill that does not exist.
* :class:`AgentSkillsError` -- base class for all library exceptions.
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
    DiscoveryNotSupportedError,
    ResourceListingNotSupportedError,
    ResourceNotFoundError,
    SectionNotFoundError,
    SkillNotFoundError,
    SkillUnavailableError,
)
from agentskills_core.fastpath import (
    DEFAULT_FAST_PATH_MAX_TOKENS,
    FAST_PATH_DROPPED_TOOLS,
    FAST_PATH_RESOURCE_INSTRUCTIONS,
    FastPath,
    resolve_fast_path,
)
from agentskills_core.logging import (
    LOGGER_NAMESPACE,
    REDACTED,
    get_logger,
    redact_url,
)
from agentskills_core.parsing import split_frontmatter
from agentskills_core.provider import RESOURCE_KINDS, SkillProvider
from agentskills_core.registry import SkillRegistry
from agentskills_core.sections import (
    PREAMBLE_TITLE,
    WHOLE_BODY_CHEAPER_TOKENS,
    Section,
    SectionRef,
    SkillOutline,
    estimate_tokens,
    outline_of,
    split_sections,
)
from agentskills_core.skill import Skill
from agentskills_core.validation import SELECTION_FIELDS, validate_skill, validate_version

__all__ = [
    "DEFAULT_FAST_PATH_MAX_TOKENS",
    "DEFAULT_MAX_INLINE_BINARY_BYTES",
    "FAST_PATH_DROPPED_TOOLS",
    "FAST_PATH_RESOURCE_INSTRUCTIONS",
    "LOGGER_NAMESPACE",
    "PREAMBLE_TITLE",
    "REDACTED",
    "RESOURCE_KINDS",
    "SELECTION_FIELDS",
    "WHOLE_BODY_CHEAPER_TOKENS",
    "AgentSkillsError",
    "DiscoveryNotSupportedError",
    "FastPath",
    "ResourceListingNotSupportedError",
    "ResourceNotFoundError",
    "Section",
    "SectionNotFoundError",
    "SectionRef",
    "Skill",
    "SkillNotFoundError",
    "SkillOutline",
    "SkillProvider",
    "SkillRegistry",
    "SkillUnavailableError",
    "encode_resource_content",
    "estimate_tokens",
    "get_logger",
    "outline_of",
    "redact_url",
    "resolve_fast_path",
    "split_frontmatter",
    "split_sections",
    "validate_skill",
    "validate_version",
]
