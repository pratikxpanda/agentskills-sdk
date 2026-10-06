"""Local filesystem-based skill provider.

This module implements :class:`LocalFileSystemSkillProvider`, which serves
`Agent Skills <https://agentskills.io>`_ from a local directory tree.
It follows the progressive-disclosure model defined in the specification:

* **Metadata** is obtained by parsing only the YAML frontmatter.
* **Body** is the markdown content after the frontmatter.
* **Resources** (scripts, references, assets) are read on demand.

The provider can enumerate itself: :meth:`LocalFileSystemSkillProvider.discover`
lists the skill directories under the root, so an application can register a
whole folder with :meth:`SkillRegistry.register_all
<agentskills_core.SkillRegistry.register_all>` instead of naming each skill.

All methods are ``async`` to satisfy the :class:`~agentskills_core.SkillProvider`
interface.  Blocking file I/O runs in a worker thread via
:func:`asyncio.to_thread`, so concurrent agent sessions are not stalled by
disk latency.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agentskills_core import (
    RESOURCE_KINDS,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillProvider,
    get_logger,
    split_frontmatter,
)

_logger = get_logger(__name__)

#: Filename that marks a directory as a skill.
SKILL_FILE_NAME: str = "SKILL.md"

#: Default maximum file size in bytes (10 MB).
DEFAULT_MAX_FILE_BYTES: int = 10 * 1024 * 1024


class LocalFileSystemSkillProvider(SkillProvider):
    """Skill provider backed by a local directory tree.

    Each immediate subdirectory of *root* that contains a ``SKILL.md``
    file is treated as a skill.  The directory name serves as the skill's
    unique identifier and must match the ``name`` field in the
    ``SKILL.md`` YAML frontmatter.

    Expected layout::

        root/
        ├── incident-response/
        │   ├── SKILL.md          # YAML frontmatter + markdown body
        │   ├── references/       # optional supplementary docs
        │   ├── scripts/          # optional executable code
        │   └── assets/           # optional static resources
        └── another-skill/
            └── SKILL.md

    Progressive disclosure guarantees:

    * :meth:`get_metadata` reads and parses only the YAML frontmatter
      (between the opening and closing ``---`` delimiters).
    * :meth:`get_body` returns only the markdown after the frontmatter.
    * Resource methods (:meth:`get_reference`, :meth:`get_script`,
      :meth:`get_asset`) read individual files on demand.  Resource
      names are discovered by the agent from the skill body.

    Args:
        root: Path to the top-level directory containing skill
            subdirectories.
        max_file_bytes: Maximum allowed file size in bytes.
            Files exceeding this limit raise
            :class:`~agentskills_core.AgentSkillsError`.  Defaults
            to 10 MB.

    ``SKILL.md`` contents are cached per provider instance after the
    first read, because a single skill is otherwise re-read up to five
    times in one agent session.  Call :meth:`invalidate` when skills
    change on disk.

    Resource listing is supported: see :meth:`list_resources`.
    Skill discovery is supported: see :meth:`discover`.

    Raises:
        NotADirectoryError: If *root* does not exist or is not a
            directory.
        ValueError: If *max_file_bytes* is negative.

    Example::

        provider = LocalFileSystemSkillProvider(Path("./skills"))
        registry = SkillRegistry()
        await registry.register_all(provider)

        skill = registry.get_skill("incident-response")
        meta = await skill.get_metadata()
        print(f"{meta['name']}: {meta['description']}")
    """

    supports_resource_listing = True
    supports_discovery = True
    supports_file_access = True

    def __init__(self, root: Path, *, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> None:
        self._root = Path(root)
        if not self._root.is_dir():
            raise NotADirectoryError(f"Skill root does not exist: {self._root}")
        if max_file_bytes < 0:
            raise ValueError("max_file_bytes must be non-negative")
        self._max_file_bytes = max_file_bytes
        self._skill_md_cache: dict[str, str] = {}

    def invalidate(self, skill_id: str | None = None) -> None:
        """Drop cached ``SKILL.md`` content.

        Args:
            skill_id: Skill to forget.  Clears the whole cache when
                omitted.  Unknown IDs are ignored.
        """
        if skill_id is None:
            self._skill_md_cache.clear()
        else:
            self._skill_md_cache.pop(skill_id, None)
        _logger.debug("Invalidated SKILL.md cache for %s", skill_id or "all skills")

    # ------------------------------------------------------------------
    # Metadata & body — parsed lazily from SKILL.md
    # ------------------------------------------------------------------

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        """Parse and return the YAML frontmatter of a skill's ``SKILL.md``.

        Only the content between the opening and closing ``---``
        delimiters is parsed.  The markdown body is discarded so that
        metadata-only queries remain lightweight.

        Args:
            skill_id: Skill name to look up.

        Returns:
            Dictionary of frontmatter key-value pairs.

        Raises:
            SkillNotFoundError: If the skill directory or ``SKILL.md``
                does not exist.
        """
        raw = await self._read_skill_md(skill_id)
        frontmatter, _ = split_frontmatter(raw)
        return frontmatter

    async def get_body(self, skill_id: str) -> str:
        """Return the markdown instruction body after the YAML frontmatter.

        Args:
            skill_id: Skill name to look up.

        Returns:
            Markdown text (may be empty if ``SKILL.md`` has no body).

        Raises:
            SkillNotFoundError: If the skill directory or ``SKILL.md``
                does not exist.
        """
        raw = await self._read_skill_md(skill_id)
        _, body = split_frontmatter(raw)
        return body

    # ------------------------------------------------------------------
    # Scripts
    # ------------------------------------------------------------------

    async def get_script(self, skill_id: str, name: str) -> bytes:
        """Read a single script file as raw bytes.

        Args:
            skill_id: Skill name.
            name: Script filename.

        Returns:
            Raw file content.

        Raises:
            ResourceNotFoundError: If the file does not exist.
        """
        return await self._read_subdir_file(skill_id, "scripts", name)

    # ------------------------------------------------------------------
    # Assets
    # ------------------------------------------------------------------

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        """Read a single asset file as raw bytes.

        Args:
            skill_id: Skill name.
            name: Asset filename.

        Returns:
            Raw file content.

        Raises:
            ResourceNotFoundError: If the file does not exist.
        """
        return await self._read_subdir_file(skill_id, "assets", name)

    # ------------------------------------------------------------------
    # References
    # ------------------------------------------------------------------

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        """Read a single reference file as raw bytes.

        Args:
            skill_id: Skill name.
            name: Reference filename.

        Returns:
            Raw file content.

        Raises:
            ResourceNotFoundError: If the file does not exist.
        """
        return await self._read_subdir_file(skill_id, "references", name)

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        """List the resource files a skill contains, grouped by kind.

        Only regular files directly inside ``references/``, ``scripts/``
        and ``assets/`` are reported.  Subdirectories, dotfiles and
        symlinks pointing outside the skill root are skipped rather than
        raising, so one stray entry cannot make a whole skill
        unlistable.

        Args:
            skill_id: Skill name.

        Returns:
            Mapping of resource kind to sorted filenames.  Categories the
            skill does not use map to an empty list.

        Raises:
            SkillNotFoundError: If the skill directory does not exist.
        """
        return await asyncio.to_thread(self._list_resources_sync, skill_id)

    async def list_files(self, skill_id: str) -> list[str]:
        """List the complete tree without reading file contents.

        Includes SKILL.md, hidden files, and arbitrary nested directories.
        Links and special files are rejected instead of silently publishing
        an incomplete manifest. Only publish a directory intended for sharing.
        """
        return await asyncio.to_thread(self._list_files_sync, skill_id)

    async def read_file(self, skill_id: str, path: str) -> bytes:
        """Read original bytes from a confined, link-free skill tree.

        This deliberately bypasses the parsed SKILL.md cache. No decoding or
        newline conversion is performed. The configured file-size limit applies.
        """
        return await asyncio.to_thread(self._read_file_sync, skill_id, path)

    def _file_skill_dir(self, skill_id: str) -> Path:
        """Validate a skill directory for complete file access."""
        if not skill_id or skill_id in {".", ".."} or any(char in skill_id for char in "/\\:\x00"):
            raise SkillNotFoundError(f"Invalid skill_id: {skill_id!r}")
        candidate = self._root / skill_id
        if candidate.is_symlink() or candidate.is_junction():
            raise SkillNotFoundError(f"Linked skill directory: {skill_id!r}")
        skill_dir = self._skill_dir(skill_id)
        skill_md = skill_dir / SKILL_FILE_NAME
        if skill_md.is_symlink() or not skill_md.is_file():
            raise SkillNotFoundError(f"Original SKILL.md not found for {skill_id!r}")
        return skill_dir

    def _file_path(self, skill_dir: Path, path: str) -> Path:
        """Reject aliases and links before resolving a skill-relative file."""
        parts = path.split("/")
        if any(part in {"", ".", ".."} for part in parts) or any(
            char in path for char in "\\:\x00"
        ):
            raise ResourceNotFoundError(f"Invalid file path: {path!r}")
        candidate = skill_dir
        for part in parts:
            candidate = candidate / part
            if candidate.is_symlink() or candidate.is_junction():
                raise ResourceNotFoundError(f"Linked skill file path: {path!r}")
        if not candidate.resolve().is_relative_to(skill_dir) or not candidate.is_file():
            raise ResourceNotFoundError(f"Skill file not found: {path!r}")
        return candidate

    def _list_files_sync(self, skill_id: str) -> list[str]:
        """Enumerate every regular file, refusing links and special files."""
        skill_dir = self._file_skill_dir(skill_id)
        pending = [skill_dir]
        paths: list[str] = []
        while pending:
            for entry in pending.pop().iterdir():
                relative = entry.relative_to(skill_dir).as_posix()
                if entry.is_symlink() or entry.is_junction():
                    raise ResourceNotFoundError(f"Linked skill file path: {relative!r}")
                if entry.is_dir():
                    pending.append(entry)
                else:
                    self._file_path(skill_dir, relative)
                    paths.append(relative)
        return sorted(paths)

    def _read_file_sync(self, skill_id: str, path: str) -> bytes:
        """Read at most the file-size limit plus one byte."""
        candidate = self._file_path(self._file_skill_dir(skill_id), path)
        with candidate.open("rb") as stream:
            data = stream.read(self._max_file_bytes + 1)
        if len(data) > self._max_file_bytes:
            raise ResourceNotFoundError(
                f"Skill file {path!r} exceeds maximum size ({self._max_file_bytes} bytes)"
            )
        return data

    async def discover(self) -> list[str]:
        """List the skill directories directly beneath the root.

        A directory counts as a skill when it holds a ``SKILL.md``.
        Dotted directories, loose files and symlinks pointing outside
        the root are skipped, matching :meth:`list_resources`.

        Discovery does not read or validate the skills it finds, so a
        returned ID can still fail registration.  That is deliberate:
        enumerating a folder should not cost one full parse per skill.

        Returns:
            Sorted skill IDs.  Empty when the root holds no skills.
        """
        return await asyncio.to_thread(self._discover_sync)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _discover_sync(self) -> list[str]:
        """Enumerate skill directories under the root."""
        root = self._root.resolve()
        skill_ids: list[str] = []

        for entry in root.iterdir():
            if entry.name.startswith("."):
                continue
            if not entry.is_dir():
                continue
            if not entry.resolve().is_relative_to(root):
                continue
            if (entry / SKILL_FILE_NAME).is_file():
                skill_ids.append(entry.name)

        _logger.debug("Discovered %d skills under %s", len(skill_ids), root)
        return sorted(skill_ids)

    def _list_resources_sync(self, skill_id: str) -> dict[str, list[str]]:
        """Enumerate a skill's resource directories."""
        skill_dir = self._skill_dir(skill_id)
        root = self._root.resolve()
        listing: dict[str, list[str]] = {}

        for kind in RESOURCE_KINDS:
            subdir = skill_dir / kind
            names: list[str] = []
            if subdir.is_dir():
                for entry in subdir.iterdir():
                    if entry.name.startswith("."):
                        continue
                    if not entry.is_file():
                        continue
                    if not entry.resolve().is_relative_to(root):
                        continue
                    names.append(entry.name)
            listing[kind] = sorted(names)

        return listing

    def _skill_dir(self, skill_id: str) -> Path:
        """Resolve and validate the directory path for a skill.

        Args:
            skill_id: Skill name (directory name).

        Returns:
            Resolved :class:`~pathlib.Path` to the skill directory.

        Raises:
            SkillNotFoundError: If the directory does not exist.
        """
        # A NUL truncates the path in the C layer. POSIX raises ValueError out
        # of lstat and Windows does not, so refuse it before resolve() sees it.
        if "\x00" in skill_id:
            raise SkillNotFoundError(f"Invalid skill_id: {skill_id!r}")
        path = (self._root / skill_id).resolve()
        if not path.is_relative_to(self._root.resolve()):
            raise SkillNotFoundError(f"Invalid skill_id: {skill_id!r}")
        if not path.is_dir():
            raise SkillNotFoundError(f"Skill not found: {skill_id!r}")
        return path

    async def _read_skill_md(self, skill_id: str) -> str:
        """Read a skill's ``SKILL.md`` without blocking the event loop."""
        cached = self._skill_md_cache.get(skill_id)
        if cached is not None:
            _logger.debug("Cache hit for SKILL.md of %r", skill_id)
            return cached
        text = await asyncio.to_thread(self._read_skill_md_sync, skill_id)
        self._skill_md_cache[skill_id] = text
        _logger.debug("Read SKILL.md for %r from disk (%d bytes)", skill_id, len(text))
        return text

    def _read_skill_md_sync(self, skill_id: str) -> str:
        """Read the full text of a skill's ``SKILL.md`` file.

        Args:
            skill_id: Skill name.

        Returns:
            UTF-8 file contents.

        Raises:
            SkillNotFoundError: If the directory or file does not exist.
        """
        skill_md = self._skill_dir(skill_id) / SKILL_FILE_NAME
        if not skill_md.is_file():
            raise SkillNotFoundError(f"SKILL.md not found for skill {skill_id!r}")
        size = skill_md.stat().st_size
        if size > self._max_file_bytes:
            raise SkillNotFoundError(
                f"SKILL.md for skill {skill_id!r} exceeds maximum size "
                f"({self._max_file_bytes} bytes)"
            )
        return skill_md.read_text(encoding="utf-8")

    async def _read_subdir_file(self, skill_id: str, subdir: str, name: str) -> bytes:
        """Read a skill resource without blocking the event loop."""
        data = await asyncio.to_thread(self._read_subdir_file_sync, skill_id, subdir, name)
        _logger.debug("Read %s/%s for %r (%d bytes)", subdir, name, skill_id, len(data))
        return data

    def _read_subdir_file_sync(self, skill_id: str, subdir: str, name: str) -> bytes:
        """Read a single file from a skill's subdirectory.

        Args:
            skill_id: Skill name.
            subdir: Subdirectory name.
            name: Filename to read.

        Returns:
            Raw file content as bytes.

        Raises:
            ResourceNotFoundError: If the file does not exist.
        """
        if "\x00" in name:
            raise ResourceNotFoundError(f"Invalid resource name: {name!r}")
        path = (self._skill_dir(skill_id) / subdir / name).resolve()
        if not path.is_relative_to(self._root.resolve()):
            raise ResourceNotFoundError(f"Invalid resource name: {name!r}")
        if not path.is_file():
            raise ResourceNotFoundError(
                f"Resource {name!r} not found in {subdir}/ for skill {skill_id!r}"
            )
        size = path.stat().st_size
        if size > self._max_file_bytes:
            raise ResourceNotFoundError(
                f"Resource {name!r} for skill {skill_id!r} exceeds maximum size "
                f"({self._max_file_bytes} bytes)"
            )
        return path.read_bytes()
