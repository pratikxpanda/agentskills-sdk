"""Locate skills on disk.

Every command takes a path that is either one skill folder or a folder
of them.  Resolving that ambiguity in one place keeps the commands from
each inventing their own answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentskills_core import get_logger

SKILL_FILE = "SKILL.md"

_logger = get_logger(__name__)


class CliError(Exception):
    """A problem with the invocation itself, not with a skill.

    Raised for a missing path or an empty directory — conditions that
    mean the command could not run, as opposed to running and finding
    fault with a skill.
    """


@dataclass(frozen=True)
class SkillLocation:
    """One skill directory and the ID it will be registered under."""

    skill_id: str
    path: Path


def discover(target: Path) -> tuple[Path, list[SkillLocation]]:
    """Resolve *target* into a provider root and the skills beneath it.

    A directory containing ``SKILL.md`` is a single skill, and its
    parent becomes the provider root because
    :class:`~agentskills_fs.LocalFileSystemSkillProvider` addresses
    skills by directory name below a root.  Any other directory is
    treated as a collection, and each immediate subdirectory holding a
    ``SKILL.md`` is one skill.

    Args:
        target: Path to a skill folder or a folder of skill folders.

    Returns:
        A ``(root, locations)`` tuple.  *locations* is sorted by skill
        ID and is never empty.

    Raises:
        CliError: If *target* is not a directory, or is a directory with
            no skills in it.
    """
    resolved = target.expanduser().resolve()

    if not resolved.is_dir():
        raise CliError(f"not a directory: {target}")

    if (resolved / SKILL_FILE).is_file():
        _logger.debug("Resolved %s as a single skill", resolved)
        return resolved.parent, [SkillLocation(resolved.name, resolved)]

    locations = [
        SkillLocation(child.name, child)
        for child in sorted(resolved.iterdir())
        if child.is_dir() and (child / SKILL_FILE).is_file()
    ]

    if not locations:
        raise CliError(
            f"no skills found in {target}: expected {SKILL_FILE} there "
            f"or in an immediate subdirectory"
        )

    _logger.debug("Resolved %s as %d skills", resolved, len(locations))
    return resolved, locations


def relative_to_cwd(path: Path) -> str:
    """Render *path* relative to the working directory when possible.

    Machine consumers annotate files by repository-relative path, so a
    relative form is preferred.  A path on another drive has no relative
    form on Windows; that falls back to absolute.
    """
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()
