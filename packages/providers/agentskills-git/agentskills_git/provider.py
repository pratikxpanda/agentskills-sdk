"""Serve Agent Skills from a Git revision pinned to its resolved commit."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path, PurePosixPath
from typing import Any

from agentskills_core import SkillProvider
from agentskills_fs import LocalFileSystemSkillProvider

DEFAULT_MAX_CACHE_BYTES = 256 * 1024 * 1024
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")


class GitSkillProviderError(RuntimeError):
    """Raised when a repository revision cannot be resolved or cached."""


class GitSkillProvider(SkillProvider):
    """Read skills from a Git repository at one immutable resolved commit.

    The configured ref is resolved on first access. The resulting commit is
    cached and exposed through :attr:`resolved_commit`; later reads use that
    checkout even if the remote ref moves. The selected directory must contain
    skill directories directly beneath it, matching the filesystem provider.

    Git hooks, system and global Git configuration, submodules, and external
    Git protocols are disabled for the fetch. Skill scripts are never run.

    Args:
        repository: Git URL or local repository path.
        ref: Branch, tag, or commit reference to resolve on first access.
        cache_dir: Directory for the pinned checkout.
        subdirectory: POSIX repository-relative directory containing skills.
        max_cache_bytes: Maximum size of the checkout and Git metadata.

    Raises:
        ValueError: If the ref, subdirectory, or cache limit is invalid.

    Example:
        >>> provider = GitSkillProvider(
        ...     "https://github.com/example/skills.git", "main", Path(".cache/skills")
        ... )
        >>> skills = await provider.discover()
    """

    supports_resource_listing = True
    supports_discovery = True
    supports_file_access = True

    def __init__(
        self,
        repository: str,
        ref: str,
        cache_dir: Path,
        *,
        subdirectory: str = ".",
        max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES,
    ) -> None:
        if not repository:
            raise ValueError("repository must not be empty")
        if not ref or ref.startswith("-") or "\x00" in ref:
            raise ValueError("ref must be a non-empty Git reference")
        if "\\" in subdirectory or "\x00" in subdirectory:
            raise ValueError("subdirectory must be a POSIX relative path")
        relative = PurePosixPath(subdirectory)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("subdirectory must stay within the repository")
        if max_cache_bytes < 0:
            raise ValueError("max_cache_bytes must be non-negative")

        self.repository = repository
        self.ref = ref
        self.cache_dir = Path(cache_dir)
        self.subdirectory = relative
        self.max_cache_bytes = max_cache_bytes
        self._lock = threading.Lock()
        self._provider: LocalFileSystemSkillProvider | None = None
        self._resolved_commit: str | None = None
        identity = "\0".join((repository, ref, relative.as_posix()))
        self._cache_path = self.cache_dir / hashlib.sha256(identity.encode()).hexdigest()

    @property
    def resolved_commit(self) -> str | None:
        """Commit SHA resolved on first access, or ``None`` before access."""
        return self._resolved_commit

    async def get_metadata(self, skill_id: str) -> dict[str, Any]:
        """Return parsed frontmatter for a skill.

        Args:
            skill_id: Skill identifier.

        Returns:
            Parsed frontmatter metadata.
        """
        return await (await self._get_provider()).get_metadata(skill_id)

    async def get_body(self, skill_id: str) -> str:
        """Return the instruction body for a skill.

        Args:
            skill_id: Skill identifier.

        Returns:
            Markdown instruction body.
        """
        return await (await self._get_provider()).get_body(skill_id)

    async def get_script(self, skill_id: str, name: str) -> bytes:
        """Return a script file without executing it.

        Args:
            skill_id: Skill identifier.
            name: Script filename.

        Returns:
            Original script bytes.
        """
        return await (await self._get_provider()).get_script(skill_id, name)

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        """Return an asset file as bytes.

        Args:
            skill_id: Skill identifier.
            name: Asset filename.

        Returns:
            Original asset bytes.
        """
        return await (await self._get_provider()).get_asset(skill_id, name)

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        """Return a reference file as bytes.

        Args:
            skill_id: Skill identifier.
            name: Reference filename.

        Returns:
            Original reference bytes.
        """
        return await (await self._get_provider()).get_reference(skill_id, name)

    async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
        """List standard resource files for a skill.

        Args:
            skill_id: Skill identifier.

        Returns:
            Resource names grouped by kind.
        """
        return await (await self._get_provider()).list_resources(skill_id)

    async def list_files(self, skill_id: str) -> list[str]:
        """List every file in a skill without reading file contents.

        Args:
            skill_id: Skill identifier.

        Returns:
            Sorted POSIX paths relative to the skill root.
        """
        return await (await self._get_provider()).list_files(skill_id)

    async def read_file(self, skill_id: str, path: str) -> bytes:
        """Read one original skill file as bytes.

        Args:
            skill_id: Skill identifier.
            path: POSIX path relative to the skill root.

        Returns:
            Original file bytes.
        """
        return await (await self._get_provider()).read_file(skill_id, path)

    async def discover(self) -> list[str]:
        """Return skill IDs directly under the configured repository path.

        Returns:
            Sorted skill identifiers.
        """
        return await (await self._get_provider()).discover()

    async def _get_provider(self) -> LocalFileSystemSkillProvider:
        return await asyncio.to_thread(self._get_provider_sync)

    def _get_provider_sync(self) -> LocalFileSystemSkillProvider:
        if self._provider is not None:
            return self._provider
        with self._lock:
            if self._provider is not None:
                return self._provider
            root, commit = self._materialize()
            self._provider = LocalFileSystemSkillProvider(root)
            self._resolved_commit = commit
            return self._provider

    def _materialize(self) -> tuple[Path, str]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self._cache_path.is_symlink() or self._cache_path.is_junction():
            raise GitSkillProviderError("Git cache entry must not be a link")
        marker = self._cache_path / ".agentskills-git-commit"
        if marker.is_file():
            commit = marker.read_text(encoding="ascii").strip()
            root = self._content_root(self._cache_path)
            if _COMMIT_PATTERN.fullmatch(commit) and root.is_dir():
                self._check_cache_size(self._cache_path)
                return root, commit
            shutil.rmtree(self._cache_path)
        elif self._cache_path.exists():
            if self._cache_path.is_dir():
                shutil.rmtree(self._cache_path)
            else:
                self._cache_path.unlink()

        try:
            with tempfile.TemporaryDirectory(prefix="agentskills-git-", dir=self.cache_dir) as temp:
                temporary_root = Path(temp)
                repo_dir = temporary_root / "repo"
                hooks = temporary_root / "hooks"
                template = temporary_root / "template"
                hooks.mkdir()
                template.mkdir()
                global_config = temporary_root / "gitconfig"
                global_config.write_text("", encoding="utf-8")
                env = os.environ.copy()
                env["GIT_CONFIG_NOSYSTEM"] = "1"
                env["GIT_CONFIG_GLOBAL"] = str(global_config)
                self._git(["init", "--quiet", f"--template={template}", str(repo_dir)], env, hooks)
                self._git(
                    ["-C", str(repo_dir), "remote", "add", "origin", self.repository],
                    env,
                    hooks,
                )
                self._git(
                    ["-C", str(repo_dir), "fetch", "--quiet", "--depth=1", "origin", self.ref],
                    env,
                    hooks,
                )
                commit = self._git(
                    ["-C", str(repo_dir), "rev-parse", "FETCH_HEAD^{commit}"], env, hooks
                ).strip()
                if not _COMMIT_PATTERN.fullmatch(commit):
                    raise GitSkillProviderError("Git returned an invalid resolved commit")
                self._git(
                    ["-C", str(repo_dir), "checkout", "--quiet", "--detach", commit], env, hooks
                )
                self._git(["-C", str(repo_dir), "remote", "remove", "origin"], env, hooks)
                (repo_dir / ".git" / "FETCH_HEAD").unlink(missing_ok=True)
                root = self._content_root(repo_dir)
                if not root.is_dir():
                    raise GitSkillProviderError(
                        "Configured subdirectory does not exist at this commit"
                    )
                self._reject_links(root)
                (repo_dir / ".agentskills-git-commit").write_text(commit, encoding="ascii")
                self._check_cache_size(repo_dir)
                shutil.move(str(repo_dir), str(self._cache_path))
                return self._content_root(self._cache_path), commit
        except GitSkillProviderError:
            raise
        except (OSError, subprocess.SubprocessError):
            raise GitSkillProviderError(
                "Could not fetch or cache the configured Git revision"
            ) from None

    def _git(self, args: list[str], env: dict[str, str], hooks: Path) -> str:
        result = subprocess.run(
            ["git", "-c", f"core.hooksPath={hooks}", "-c", "protocol.ext.allow=never", *args],
            capture_output=True,
            check=True,
            env=env,
            text=True,
            timeout=120,
        )
        return result.stdout

    def _content_root(self, repo_dir: Path) -> Path:
        root = repo_dir.resolve()
        candidate = repo_dir
        for part in self.subdirectory.parts:
            candidate = candidate / part
            if candidate.is_symlink() or candidate.is_junction():
                raise GitSkillProviderError("Configured subdirectory contains a link")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise GitSkillProviderError("Configured subdirectory escapes the checkout")
        return resolved

    def _check_cache_size(self, repo_dir: Path) -> None:
        size = 0
        for path in repo_dir.rglob("*"):
            if path.is_symlink():
                raise GitSkillProviderError("Repository checkout contains a symbolic link")
            if path.is_file():
                size += path.stat().st_size
                if size > self.max_cache_bytes:
                    raise GitSkillProviderError(
                        f"Repository checkout exceeds max_cache_bytes ({self.max_cache_bytes})"
                    )

    @staticmethod
    def _reject_links(repo_dir: Path) -> None:
        for path in repo_dir.rglob("*"):
            if path.is_symlink():
                raise GitSkillProviderError("Repository checkout contains a symbolic link")
