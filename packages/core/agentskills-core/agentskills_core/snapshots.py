"""Bounded, byte-preserving captures for consistent skill delivery."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from agentskills_core.exceptions import (
    FileAccessNotSupportedError,
    ResourceNotFoundError,
    SkillUnavailableError,
)
from agentskills_core.skill import Skill

DEFAULT_SNAPSHOT_MAX_FILES = 512
DEFAULT_SNAPSHOT_MAX_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SkillFile:
    """One captured file with a digest computed from its original bytes."""

    path: str
    data: bytes
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", "sha256:" + sha256(self.data).hexdigest())

    @property
    def size(self) -> int:
        """Return the raw byte count, before any transport encoding."""
        return len(self.data)


@dataclass(frozen=True, slots=True)
class SkillSnapshot:
    """An immutable file set captured from one skill.

    The source must be trusted and immutable during capture. Repeated reads
    detect ordinary concurrent changes, but are not a filesystem transaction
    or a defense against a malicious provider. Later source changes cannot
    affect the captured files. Digests establish consistency, not publisher trust.
    """

    skill_id: str
    files: tuple[SkillFile, ...]

    @property
    def total_bytes(self) -> int:
        """Return the sum of all captured file sizes."""
        return sum(file.size for file in self.files)

    def get_file(self, path: str) -> SkillFile:
        """Look up an exact relative path without contacting the provider."""
        for file in self.files:
            if file.path == path:
                return file
        raise ResourceNotFoundError(f"Skill '{self.skill_id}' has no captured file '{path}'")


def _paths(paths: list[str], max_files: int) -> tuple[str, ...]:
    if len(paths) > max_files:
        raise ValueError(f"Skill exceeds the {max_files}-file snapshot limit")
    if not all(
        isinstance(path, str)
        and not any(char in path for char in "\\:\0")
        and all(part not in {"", ".", ".."} for part in path.split("/"))
        for path in paths
    ):
        raise ValueError("Skill file listing contains an unsafe relative path")
    if len(set(paths)) != len(paths) or "SKILL.md" not in paths:
        raise ValueError("Skill file listing must be unique and include SKILL.md")
    return tuple(sorted(paths))


async def capture_skill(
    skill: Skill,
    *,
    max_files: int = DEFAULT_SNAPSHOT_MAX_FILES,
    max_total_bytes: int = DEFAULT_SNAPSHOT_MAX_BYTES,
) -> SkillSnapshot:
    """Capture and verify a complete file set, failing without a partial result.

    Defaults match the MCP Skills extension's per-skill delivery limits.
    Callers must also bound the number of retained snapshots. Provider reads
    must enforce their own per-file bounds, as bytes arrive already allocated.

    Raises:
        FileAccessNotSupportedError: The skill lacks lossless file access.
        ValueError: A limit, listing, or returned file is invalid.
        SkillUnavailableError: The source changed during capture.
    """
    if max_files < 1 or max_total_bytes < 0:
        raise ValueError("Snapshot limits require max_files >= 1 and max_total_bytes >= 0")
    if not skill.supports_file_access:
        raise FileAccessNotSupportedError(f"Skill '{skill.get_id()}' lacks lossless file access")
    paths = _paths(await skill.list_files(), max_files)
    files: list[SkillFile] = []
    total = 0
    for path in paths:
        data = await skill.read_file(path)
        if not isinstance(data, bytes):
            raise ValueError("Lossless file reads must return bytes")
        total += len(data)
        if total > max_total_bytes:
            raise ValueError(f"Skill exceeds the {max_total_bytes}-byte snapshot limit")
        files.append(SkillFile(path, data))
    if _paths(await skill.list_files(), max_files) != paths:
        raise SkillUnavailableError(f"Skill '{skill.get_id()}' file listing changed during capture")
    for file in files:
        if await skill.read_file(file.path) != file.data:
            raise SkillUnavailableError(
                f"Skill '{skill.get_id()}' file content changed during capture"
            )
    return SkillSnapshot(skill.get_id(), tuple(files))
