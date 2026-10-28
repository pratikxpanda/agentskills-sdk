"""Tests for the Git-backed provider."""

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from agentskills_core import SkillRegistry
from agentskills_git import GitSkillProvider, GitSkillProviderError


def _git(args: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture()
def git_source(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    source = tmp_path / "source"
    bare = tmp_path / "skills.git"
    source.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    _git(["init", "-b", "main"], cwd=source, env=env)
    skill = source / "incident-response"
    skill.mkdir()
    (skill / "SKILL.md").write_bytes(
        b"---\nname: incident-response\ndescription: Handle incidents.\n---\n\n# First\n"
    )
    for directory, name, content in (
        ("scripts", "run.sh", b"echo safe"),
        ("assets", "map.bin", b"\x00\xff"),
        ("references", "guide.md", b"reference"),
    ):
        resource_dir = skill / directory
        resource_dir.mkdir()
        (resource_dir / name).write_bytes(content)
    _git(["add", "."], cwd=source, env=env)
    _git(["commit", "-m", "first"], cwd=source, env=env)
    _git(["clone", "--bare", str(source), str(bare)], cwd=tmp_path, env=env)
    return source, bare, env


class TestGitSkillProvider:
    @pytest.mark.parametrize(
        ("repository", "ref", "subdirectory", "max_cache_bytes", "message"),
        [
            ("", "main", ".", 1, "repository must not be empty"),
            ("repo", "", ".", 1, "ref must be a non-empty Git reference"),
            ("repo", "--help", ".", 1, "ref must be a non-empty Git reference"),
            ("repo", "main", "a\\b", 1, "POSIX relative path"),
            ("repo", "main", "a\x00b", 1, "POSIX relative path"),
            ("repo", "main", "/outside", 1, "stay within the repository"),
            ("repo", "main", ".", -1, "max_cache_bytes must be non-negative"),
        ],
    )
    def test_given_invalid_configuration_when_initialized_then_raises_value_error(
        self,
        tmp_path: Path,
        repository: str,
        ref: str,
        subdirectory: str,
        max_cache_bytes: int,
        message: str,
    ) -> None:
        with pytest.raises(ValueError, match=message):
            GitSkillProvider(
                repository,
                ref,
                tmp_path,
                subdirectory=subdirectory,
                max_cache_bytes=max_cache_bytes,
            )

    async def test_given_branch_when_discovered_then_pins_commit_and_reads_skill(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        _, bare, _ = git_source
        provider = GitSkillProvider(str(bare), "main", tmp_path / "cache")

        skills = await provider.discover()

        assert skills == ["incident-response"]
        assert provider.resolved_commit is not None
        assert len(provider.resolved_commit) in {40, 64}
        assert str(bare) not in (provider._cache_path / ".git" / "config").read_text(
            encoding="utf-8"
        )
        assert not (provider._cache_path / ".git" / "FETCH_HEAD").exists()
        assert await provider.get_metadata("incident-response") == {
            "name": "incident-response",
            "description": "Handle incidents.",
        }
        assert "# First" in await provider.get_body("incident-response")
        assert await provider.get_script("incident-response", "run.sh") == b"echo safe"
        assert await provider.get_asset("incident-response", "map.bin") == b"\x00\xff"
        assert await provider.get_reference("incident-response", "guide.md") == b"reference"
        assert await provider.list_resources("incident-response") == {
            "references": ["guide.md"],
            "scripts": ["run.sh"],
            "assets": ["map.bin"],
        }
        assert await provider.list_files("incident-response") == [
            "SKILL.md",
            "assets/map.bin",
            "references/guide.md",
            "scripts/run.sh",
        ]
        assert b"# First" in await provider.read_file("incident-response", "SKILL.md")
        cached_provider = provider._get_provider_sync()
        assert provider._get_provider_sync() is cached_provider

        registry = SkillRegistry()
        assert await registry.register_all(provider) == ["incident-response"]

    async def test_given_moved_branch_when_provider_reused_then_keeps_resolved_commit(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        source, bare, env = git_source
        cache = tmp_path / "cache"
        first = GitSkillProvider(str(bare), "main", cache)
        first_commit = first.resolved_commit

        await first.discover()
        first_commit = first.resolved_commit
        (source / "incident-response" / "SKILL.md").write_text(
            "---\nname: incident-response\ndescription: Updated.\n---\n\n# Second\n",
            encoding="utf-8",
        )
        _git(["add", "."], cwd=source, env=env)
        _git(["commit", "-m", "second"], cwd=source, env=env)
        _git(["push", str(bare), "main"], cwd=source, env=env)

        second = GitSkillProvider(str(bare), "main", cache)

        assert await second.get_metadata("incident-response") == {
            "name": "incident-response",
            "description": "Handle incidents.",
        }
        assert second.resolved_commit == first_commit

    def test_given_parent_subdirectory_when_initialized_then_rejects_path_escape(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="stay within the repository"):
            GitSkillProvider("repo", "main", tmp_path, subdirectory="../outside")

    def test_given_symlinked_subdirectory_when_resolved_then_rejects_link(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        link = checkout / "skills"
        monkeypatch.setattr(type(link), "is_symlink", lambda path: path == link)
        provider = GitSkillProvider("repo", "main", tmp_path / "cache", subdirectory="skills")

        with pytest.raises(GitSkillProviderError, match="contains a link"):
            provider._content_root(checkout)

    def test_given_linked_cache_entry_when_materialized_then_rejects_link(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = GitSkillProvider("repo", "main", tmp_path)
        cache_entry = provider._cache_path
        monkeypatch.setattr(type(cache_entry), "is_symlink", lambda path: path == cache_entry)

        with pytest.raises(GitSkillProviderError, match="cache entry must not be a link"):
            provider._materialize()

    async def test_given_cache_parent_hook_when_checkout_then_does_not_run(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        _, bare, _ = git_source
        cache = tmp_path / "cache"
        cache.mkdir()
        marker = tmp_path / "hook-ran"
        hook = cache / "post-checkout"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
        hook.chmod(0o755)
        provider = GitSkillProvider(str(bare), "main", cache)

        await provider.discover()

        assert not marker.exists()

    async def test_given_stricter_cache_limit_when_reusing_checkout_then_rejects_cache(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        _, bare, _ = git_source
        cache = tmp_path / "cache"
        initial = GitSkillProvider(str(bare), "main", cache)
        await initial.discover()
        strict = GitSkillProvider(str(bare), "main", cache, max_cache_bytes=1)

        with pytest.raises(GitSkillProviderError, match="exceeds max_cache_bytes"):
            await strict.discover()

    async def test_given_cache_limit_smaller_than_marker_when_materialized_then_cleans_cache(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        _, bare, _ = git_source
        initial = GitSkillProvider(str(bare), "main", tmp_path / "initial")
        await initial.discover()
        current_size = sum(
            path.stat().st_size for path in initial._cache_path.rglob("*") if path.is_file()
        )
        cache = tmp_path / "limited"
        limited = GitSkillProvider(str(bare), "main", cache, max_cache_bytes=current_size - 1)

        with pytest.raises(GitSkillProviderError, match="exceeds max_cache_bytes"):
            await limited.discover()

        assert not limited._cache_path.exists()

    async def test_given_invalid_cached_commit_marker_when_discovered_then_refetches(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        _, bare, _ = git_source
        cache = tmp_path / "cache"
        identity = "\0".join((str(bare), "main", "."))
        checkout = cache / hashlib.sha256(identity.encode()).hexdigest()
        checkout.mkdir(parents=True)
        (checkout / ".agentskills-git-commit").write_text("invalid", encoding="ascii")
        provider = GitSkillProvider(str(bare), "main", cache)

        assert await provider.discover() == ["incident-response"]

    async def test_given_partial_cache_entry_when_discovered_then_refetches(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        _, bare, _ = git_source
        cache = tmp_path / "cache"
        provider = GitSkillProvider(str(bare), "main", cache)
        provider._cache_path.mkdir(parents=True)
        (provider._cache_path / "partial").write_text("interrupted", encoding="utf-8")

        assert await provider.discover() == ["incident-response"]

    async def test_given_file_cache_entry_when_discovered_then_refetches(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        _, bare, _ = git_source
        cache = tmp_path / "cache"
        provider = GitSkillProvider(str(bare), "main", cache)
        cache.mkdir()
        provider._cache_path.write_text("interrupted", encoding="utf-8")

        assert await provider.discover() == ["incident-response"]

    async def test_given_missing_subdirectory_when_discovered_then_raises_provider_error(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        _, bare, _ = git_source
        provider = GitSkillProvider(str(bare), "main", tmp_path / "cache", subdirectory="missing")

        with pytest.raises(GitSkillProviderError, match="subdirectory does not exist"):
            await provider.discover()

    async def test_given_invalid_resolved_commit_when_discovered_then_rejects_commit(
        self,
        git_source: tuple[Path, Path, dict[str, str]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _, bare, _ = git_source
        provider = GitSkillProvider(str(bare), "main", tmp_path / "cache")

        def invalid_commit(args: list[str], env: dict[str, str], hooks: Path) -> str:
            return "invalid" if "rev-parse" in args else ""

        monkeypatch.setattr(provider, "_git", invalid_commit)

        with pytest.raises(GitSkillProviderError, match="invalid resolved commit"):
            await provider.discover()

    async def test_given_unknown_ref_when_discovered_then_raises_provider_error(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        _, bare, _ = git_source
        provider = GitSkillProvider(str(bare), "missing-ref", tmp_path / "cache")

        with pytest.raises(GitSkillProviderError, match="Could not fetch or cache"):
            await provider.discover()

    async def test_given_git_executable_failure_when_discovered_then_wraps_os_error(
        self,
        git_source: tuple[Path, Path, dict[str, str]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _, bare, _ = git_source

        def fail_git(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise OSError("Git executable unavailable")

        monkeypatch.setattr(subprocess, "run", fail_git)
        provider = GitSkillProvider(str(bare), "main", tmp_path / "cache")

        with pytest.raises(GitSkillProviderError, match="Could not fetch or cache"):
            await provider.discover()
