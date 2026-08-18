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

import re
from typing import TYPE_CHECKING

from agentskills_core.logging import get_logger

if TYPE_CHECKING:
    from agentskills_core.skill import Skill

_logger = get_logger(__name__)

# Agent Skills spec: name must be 1-64 chars, lowercase alphanumeric + hyphens,
# must not start/end with hyphen, must not contain consecutive hyphens.
_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_NAME_MAX_LEN = 64
_DESCRIPTION_MAX_LEN = 1024

# The official semver.org grammar. Kept inline rather than taking a
# dependency: agentskills-core deliberately depends only on pyyaml.
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

# Known optional fields with their expected types.
_OPTIONAL_FIELDS: dict[str, type] = {
    "license": str,
    "compatibility": dict,
    "metadata": dict,
    "allowed-tools": list,
    "when_to_use": list,
    "when_not_to_use": list,
}

_KNOWN_KEYS: frozenset[str] = frozenset(
    {"name", "description", "version"} | _OPTIONAL_FIELDS.keys()
)

#: Fields describing when a skill does and does not apply.
SELECTION_FIELDS: tuple[str, ...] = ("when_to_use", "when_not_to_use")

# Selection metadata rides in the catalog, which is charged on every turn
# for every registered skill, so it is bounded on both axes. Five is also
# a design signal: a skill needing a sixth condition is two skills.
_SELECTION_ENTRY_MAX_LEN = 200
_SELECTION_MAX_ENTRIES = 5


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
    * ``version`` (optional) -- valid semver when present.  Not yet part
      of the upstream specification; see :func:`validate_version`.
    * ``when_to_use`` / ``when_not_to_use`` (optional) -- lists of at
      most five non-empty strings of at most 200 characters each.  They
      are charged on every turn, so they are bounded; see
      :data:`SELECTION_FIELDS`.

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

        # when_to_use / when_not_to_use — optional, bounded lists of strings
        for key in SELECTION_FIELDS:
            value = metadata.get(key)
            if isinstance(value, list):
                errors.extend(_selection_errors(skill_id, key, value))

        # version — optional, semver when present
        if "version" in metadata:
            version_error = validate_version(metadata["version"])
            if version_error is not None:
                errors.append(f"Skill '{skill_id}': {version_error}")

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


def _selection_errors(skill_id: str, key: str, entries: list[object]) -> list[str]:
    """Check one selection-metadata list against its element rules.

    An empty list is valid and meaningful: it says the author considered
    the question and found no conditions, which is not the same as never
    having asked.  The type of *entries* is checked by the caller.
    """
    errors: list[str] = []
    if len(entries) > _SELECTION_MAX_ENTRIES:
        errors.append(
            f"Skill '{skill_id}': field '{key}' has {len(entries)} entries, "
            f"over the limit of {_SELECTION_MAX_ENTRIES}; it is charged on every "
            f"turn, and a skill needing more conditions is probably two skills"
        )

    for index, entry in enumerate(entries):
        if not isinstance(entry, str):
            errors.append(
                f"Skill '{skill_id}': field '{key}' entry {index} must be str, "
                f"got {type(entry).__name__}"
            )
        elif not entry.strip():
            errors.append(f"Skill '{skill_id}': field '{key}' entry {index} is empty")
        elif len(entry) > _SELECTION_ENTRY_MAX_LEN:
            errors.append(
                f"Skill '{skill_id}': field '{key}' entry {index} is "
                f"{len(entry)} characters, over the limit of {_SELECTION_ENTRY_MAX_LEN}"
            )

    return errors


def validate_version(value: object) -> str | None:
    """Check a frontmatter ``version`` value, returning an error or ``None``.

    ``version`` is **not** part of the upstream Agent Skills
    specification.  It is supported here as an optional extension so
    that consumers can pin, compare, and detect drift; absence is always
    valid.

    Args:
        value: The raw value parsed from YAML frontmatter.

    Returns:
        A human-readable error message, or ``None`` when *value* is a
        valid semver string.
    """
    if not isinstance(value, str):
        # YAML types this before we see it: 1.0 is a float, 1 an int,
        # 2024-01-15 a date. Say so, or the author sees a bare type name.
        return (
            f"version must be a quoted string, got {type(value).__name__} ({value!r}). "
            f"Unquoted YAML reads 1.0 as a number and 2024-01-15 as a date — "
            f'write version: "1.0.0"'
        )
    if not _SEMVER_RE.match(value):
        return (
            f"version '{value}' is not valid semver. Expected MAJOR.MINOR.PATCH "
            f"with optional pre-release and build metadata, e.g. '1.0.0', "
            f"'2.1.0-rc.1', '1.0.0+build.5'"
        )
    return None
