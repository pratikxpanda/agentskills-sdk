"""Shared parsing utilities for Agent Skills content.

This module provides helpers used by multiple skill providers to parse
``SKILL.md`` files.  Extracting them into core avoids duplication across
provider implementations.
"""

from __future__ import annotations

from typing import Any

import yaml


def split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Split ``SKILL.md`` content into YAML frontmatter and markdown body.

    Frontmatter is the YAML block delimited by ``---`` on its own line
    at the very start of the file.  If no valid frontmatter is detected
    the entire content is returned as the body with an empty dict.

    Args:
        raw: Full text content of a ``SKILL.md`` file.

    Returns:
        A ``(frontmatter_dict, body_str)`` tuple.  *frontmatter_dict*
        is ``{}`` when no frontmatter is present.

    Example::

        meta, body = split_frontmatter(Path("SKILL.md").read_text())
        print(meta.get("name"))
    """
    if not raw.startswith("---"):
        return {}, raw

    end = raw.find("---", 3)
    if end == -1:
        return {}, raw

    fm_text = raw[3:end].strip()
    body = raw[end + 3 :].strip()
    try:
        metadata = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return {}, raw
    return metadata, body
