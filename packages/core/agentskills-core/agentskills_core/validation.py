"""Validate skills against the Agent Skills specification.

This module implements the validation rules defined in the
`Agent Skills specification <https://agentskills.io/specification>`_,
covering frontmatter field presence, format constraints, and naming
conventions.

The primary entry-point is :func:`validate_skill`, which accepts a
:class:`~agentskills_core.Skill` and returns a list of human-readable
error strings (empty if the skill is valid).

Example::

    from agentskills_core import Skill, validate_skill

    skill = Skill(skill_id="incident-response", provider=provider)
    errors = await validate_skill(skill)
    if errors:
        for msg in errors:
            print(f"  - {msg}")
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentskills_core.skill import Skill

_logger = logging.getLogger(__name__)

# Agent Skills spec: name must be 1-64 chars, lowercase alphanumeric + hyphens,
# must not start/end with hyphen, must not contain consecutive hyphens.
_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_NAME_MAX_LEN = 64
_DESCRIPTION_MAX_LEN = 1024

# Known optional fields with their expected types.
_OPTIONAL_FIELDS: dict[str, type] = {
    "license": str,
    "compatibility": dict,
    "metadata": dict,
    "allowed-tools": list,
}

_KNOWN_KEYS: frozenset[str] = frozenset({"name", "description"} | _OPTIONAL_FIELDS.keys())


async def validate_skill(skill: Skill) -> list[str]:
    """Validate a single skill against the Agent Skills specification.

    Checks that the skill's definition is well-formed and that its
    frontmatter satisfies all required and optional field constraints.

    Validation rules:

    * Skill body must be non-empty.
    * ``name`` (required) -- 1-64 characters, lowercase ``[a-z0-9-]``,
      must not start or end with a hyphen, must not contain consecutive
      hyphens, and must match the skill ID.
    * ``description`` (required) -- 1-1024 characters.

    Args:
        skill: The :class:`~agentskills_core.Skill` to validate.

    Returns:
        A list of human-readable error messages.  An empty list means
        the skill is valid.
    """
    errors: list[str] = []
    skill_id = skill.get_id()

    # Check body exists
    try:
        body = await skill.get_body()
        if not body or not body.strip():
            errors.append(f"Skill '{skill_id}': body is empty")
    except Exception as exc:
        errors.append(f"Skill '{skill_id}': failed to read body — {exc}")

    # Check metadata
    try:
        metadata = await skill.get_metadata()

        # name — required
        name = metadata.get("name")
        if not name:
            errors.append(f"Skill '{skill_id}': metadata missing required 'name' field")
        else:
            if len(name) > _NAME_MAX_LEN:
                errors.append(f"Skill '{skill_id}': name exceeds {_NAME_MAX_LEN} characters")
            if "--" in name:
                errors.append(f"Skill '{skill_id}': name contains consecutive hyphens")
            if not _NAME_RE.match(name):
                errors.append(
                    f"Skill '{skill_id}': name must be lowercase alphanumeric "
                    f"and hyphens, must not start or end with a hyphen"
                )
            if name != skill_id:
                errors.append(
                    f"Skill '{skill_id}': metadata name '{name}' "
                    f"does not match skill_id '{skill_id}'"
                )

        # description — required
        description = metadata.get("description")
        if not description:
            errors.append(f"Skill '{skill_id}': metadata missing required 'description' field")
        elif len(description) > _DESCRIPTION_MAX_LEN:
            errors.append(
                f"Skill '{skill_id}': description exceeds {_DESCRIPTION_MAX_LEN} characters"
            )

        # optional field types
        for key, expected_type in _OPTIONAL_FIELDS.items():
            value = metadata.get(key)
            if value is not None and not isinstance(value, expected_type):
                errors.append(
                    f"Skill '{skill_id}': field '{key}' must be "
                    f"{expected_type.__name__}, got {type(value).__name__}"
                )

        # unknown keys
        unknown = set(metadata.keys()) - _KNOWN_KEYS
        if unknown:
            _logger.warning(
                "Skill '%s': unknown metadata keys: %s",
                skill_id,
                ", ".join(sorted(unknown)),
            )

    except Exception as exc:
        errors.append(f"Skill '{skill_id}': failed to read metadata — {exc}")

    return errors
