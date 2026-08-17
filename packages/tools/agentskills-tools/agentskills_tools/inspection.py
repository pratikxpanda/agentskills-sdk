"""``agentskills inspect`` — show what an agent would actually receive.

A skill is only as good as what lands in the context window, and that
is not the file on disk: it is the catalog entry plus, once the agent
asks for it, the body.  Showing both with their estimated cost lets an
author see the price before shipping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

from agentskills_core import Skill, SkillRegistry, get_logger
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_tools.discovery import CliError, SkillLocation, relative_to_cwd
from agentskills_tools.lint import estimate_tokens

_logger = get_logger(__name__)


async def inspect_location(root: Path, location: SkillLocation) -> dict[str, Any]:
    """Return everything ``inspect`` reports for one skill.

    Raises:
        CliError: If the skill does not validate.  Registration is what
            an application would do, so failing here is the truthful
            answer rather than rendering something no agent could load.
    """
    provider = LocalFileSystemSkillProvider(root)
    registry = SkillRegistry()
    try:
        await registry.register(location.skill_id, provider)
    except ValueError as exc:
        raise CliError(
            f"cannot inspect '{location.skill_id}': it does not validate — {exc}"
        ) from exc

    skill = Skill(location.skill_id, provider)
    metadata = await skill.get_metadata()
    body = await skill.get_body()
    catalog = await registry.get_skills_catalog(format="xml")
    resources = await skill.list_resources() if skill.supports_resource_listing else {}

    _logger.debug("Inspected %s", location.skill_id)
    return {
        "id": location.skill_id,
        "path": relative_to_cwd(location.path),
        "metadata": metadata,
        "catalogEntry": catalog,
        "body": body,
        "resources": resources,
        "estimatedTokens": {
            "catalogEntry": estimate_tokens(catalog),
            "body": estimate_tokens(body),
        },
    }


def render_inspection_text(inspection: dict[str, Any], out: TextIO) -> None:
    """Write one inspection in human-readable form."""
    tokens = inspection["estimatedTokens"]
    print(f"{inspection['path']}  ({inspection['id']})", file=out)

    print("\nmetadata", file=out)
    for key, value in inspection["metadata"].items():
        print(f"  {key}: {value}", file=out)

    resources = inspection["resources"]
    print("\nresources", file=out)
    if any(resources.values()):
        for kind, names in resources.items():
            for name in names:
                print(f"  {kind}/{name}", file=out)
    else:
        print("  none", file=out)

    print(f"\ncatalog entry  (~{tokens['catalogEntry']} tokens, always in context)", file=out)
    print(inspection["catalogEntry"], file=out)

    print(f"\nbody  (~{tokens['body']} tokens, loaded on demand)", file=out)
    print(inspection["body"], file=out)
