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
interface.  File I/O is synchronous internally because skill files are
small and local disk reads do not meaningfully block the event loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentskills_core import (
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

    def __init__(self, root: Path, *, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> None:
        self._root = Path(root)
        if not self._root.is_dir():
            raise NotADirectoryError(f"Skill root does not exist: {self._root}")
        self._max_file_bytes = max_file_bytes

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
        raw = self._read_skill_md(skill_id)
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
        raw = self._read_skill_md(skill_id)
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
        return self._read_subdir_file(skill_id, "scripts", name)

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
        return self._read_subdir_file(skill_id, "assets", name)

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
        return self._read_subdir_file(skill_id, "references", name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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

    def _read_skill_md(self, skill_id: str) -> str:
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

    def _read_subdir_file(self, skill_id: str, subdir: str, name: str) -> bytes:
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
