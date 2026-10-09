"""``agentskills inspect`` — show what an agent would actually receive.

A skill is only as good as what lands in the context window, and that
is not the file on disk: it is the catalog entry plus, once the agent
asks for it, the body.  Showing both with their estimated cost lets an
author see the price before shipping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

from agentskills_core import (
    AgentSkillsError,
    Skill,
    SkillRegistry,
    build_skill_manifest,
    capture_skill,
    get_logger,
)
from agentskills_core.snapshots import DEFAULT_SNAPSHOT_MAX_BYTES, DEFAULT_SNAPSHOT_MAX_FILES
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_tools.discovery import CliError, SkillLocation, relative_to_cwd
from agentskills_tools.lint import estimate_tokens

_logger = get_logger(__name__)


async def inspect_native_location(
    root: Path,
    location: SkillLocation,
    *,
    max_file_bytes: int = DEFAULT_SNAPSHOT_MAX_BYTES,
) -> dict[str, Any]:
    """Check one local skill's complete native manifest without requiring MCP.

    This reads all source files to validate an immutable snapshot. It is an
    offline publication check, not metadata-only client discovery, a live
    protocol probe, or validation of an entire server's publication namespace.

    Raises:
        CliError: If the source cannot produce a bounded, valid native manifest.
    """
    try:
        provider = LocalFileSystemSkillProvider(root, max_file_bytes=max_file_bytes)
        snapshot = await capture_skill(Skill(location.skill_id, provider))
        manifest = build_skill_manifest(snapshot)
    except (AgentSkillsError, OSError, ValueError) as exc:
        raise CliError(f"cannot inspect native skill '{location.skill_id}': {exc}") from exc

    return {
        "id": location.skill_id,
        "path": relative_to_cwd(location.path),
        "scope": "localSkillSnapshot",
        "manifest": manifest,
        "fileCount": len(snapshot.files),
        "totalBytes": snapshot.total_bytes,
        "limits": {
            "maxFiles": DEFAULT_SNAPSHOT_MAX_FILES,
            "maxSkillBytes": DEFAULT_SNAPSHOT_MAX_BYTES,
            "maxFileBytes": max_file_bytes,
        },
        "protocolRequirements": {
            "version": "2026-07-28",
            "extension": "io.modelcontextprotocol/skills",
            "resources": True,
            "directoryRead": False,
        },
    }


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


def render_native_inspection_text(inspection: dict[str, Any], out: TextIO) -> None:
    """Write a native snapshot report without implying a live server probe."""
    manifest = inspection["manifest"]
    requirements = inspection["protocolRequirements"]
    limits = inspection["limits"]
    print(f"{inspection['path']}  ({inspection['id']})", file=out)
    print(f"\nnative manifest  {manifest['uri']}", file=out)
    print(f"protocol required  {requirements['version']}", file=out)
    print(f"extension required  {requirements['extension']}", file=out)
    print("resources required, directoryRead not advertised", file=out)
    print(
        f"snapshot checked  {inspection['fileCount']} files, {inspection['totalBytes']} bytes",
        file=out,
    )
    print(
        f"limits  {limits['maxFiles']} files, {limits['maxSkillBytes']} bytes per skill, "
        f"{limits['maxFileBytes']} bytes per file",
        file=out,
    )
    for resource in manifest["resources"]:
        print(f"  {resource['uri']} ({resource['size']} bytes, {resource['digest']})", file=out)
    print("\nOffline local snapshot check, not live server or host verification.", file=out)
    print(
        "Clients need the Skills extension. Tools-only clients cannot discover these skills.",
        file=out,
    )


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
