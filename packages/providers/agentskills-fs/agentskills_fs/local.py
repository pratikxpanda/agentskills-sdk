"""Local filesystem-based skill provider.

This module implements :class:`LocalFileSystemSkillProvider`, which serves
`Agent Skills <https://agentskills.io>`_ from a local directory tree.
It follows the progressive-disclosure model defined in the specification:

* **Metadata** is obtained by parsing only the YAML frontmatter.
* **Body** is the markdown content after the frontmatter.
* **Resources** (scripts, references, assets) are read on demand.

The provider is a pure content accessor — it does not enumerate or
discover skills.  Registration is handled explicitly by the application
via :meth:`SkillRegistry.register <agentskills_core.SkillRegistry.register>`.

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
    split_frontmatter,
)

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

    Raises:
        NotADirectoryError: If *root* does not exist or is not a
            directory.

    Example::

        provider = LocalFileSystemSkillProvider(Path("./skills"))
        registry = SkillRegistry()
        await registry.register("incident-response", provider)

        skill = registry.get_skill("incident-response")
        meta = await skill.get_metadata()
        print(f"{meta['name']}: {meta['description']}")
    """

    supports_resource_listing = True

    def __init__(self, root: Path, *, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> None:
        self._root = Path(root)
        if not self._root.is_dir():
            raise NotADirectoryError(f"Skill root does not exist: {self._root}")
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
            return cached
        text = await asyncio.to_thread(self._read_skill_md_sync, skill_id)
        self._skill_md_cache[skill_id] = text
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
        skill_md = self._skill_dir(skill_id) / "SKILL.md"
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
        return await asyncio.to_thread(self._read_subdir_file_sync, skill_id, subdir, name)

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
