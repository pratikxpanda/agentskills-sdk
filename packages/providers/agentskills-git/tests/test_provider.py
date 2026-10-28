"""Tests for the Git-backed provider."""

import gc
import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import agentskills_git.provider as git_provider_module
from agentskills_core import SkillRegistry, capture_skill
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
    @pytest.mark.parametrize("windows", [False, True])
    def test_given_platform_lock_backend_when_locking_then_uses_platform_api(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: bool
    ) -> None:
        calls: list[tuple[int, int]] = []
        lock_api = (
            SimpleNamespace(
                LK_LOCK=1,
                LK_NBLCK=2,
                LK_UNLCK=3,
                locking=lambda descriptor, mode, count: calls.append((mode, count)),
            )
            if windows
            else SimpleNamespace(
                LOCK_EX=4,
                LOCK_NB=8,
                LOCK_UN=16,
                flock=lambda descriptor, mode: calls.append((mode, 1)),
            )
        )
        module_name = "msvcrt" if windows else "fcntl"
        monkeypatch.setattr(git_provider_module, "_is_windows", lambda: windows)
        monkeypatch.setitem(sys.modules, module_name, lock_api)

        with (tmp_path / "lock").open("w+b") as stream:
            git_provider_module._lock_file(stream, blocking=False)
            git_provider_module._unlock_file(stream)

        assert len(calls) == 2

    def test_given_contended_windows_lock_when_blocking_then_retries_until_acquired(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts: list[int] = []

        def lock(descriptor: int, mode: int, count: int) -> None:
            attempts.append(mode)
            if len(attempts) == 1:
                raise PermissionError(13, "lock is held")

        lock_api = SimpleNamespace(LK_NBLCK=2, LK_UNLCK=3, locking=lock)
        monkeypatch.setattr(git_provider_module, "_is_windows", lambda: True)
        monkeypatch.setattr(git_provider_module.time, "sleep", lambda seconds: None)
        monkeypatch.setitem(sys.modules, "msvcrt", lock_api)

        with (tmp_path / "lock").open("w+b") as stream:
            git_provider_module._lock_file(stream, blocking=True)
            git_provider_module._unlock_file(stream)

        assert attempts == [lock_api.LK_NBLCK, lock_api.LK_NBLCK, lock_api.LK_UNLCK]

    def test_given_lease_lock_failure_when_created_then_removes_partial_lease(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = GitSkillProvider("repo", "main", tmp_path)

        def fail_lock(stream: object, *, blocking: bool) -> None:
            raise OSError("lock unavailable")

        monkeypatch.setattr(git_provider_module, "_lock_file", fail_lock)

        with pytest.raises(OSError, match="lock unavailable"):
            provider._create_cache_lease()

        lease_dir = tmp_path / ".leases" / provider._cache_path.name
        assert list(lease_dir.iterdir()) == []

    def test_given_release_lock_failure_when_released_then_removes_lease(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lease = tmp_path / "lease"
        lease.write_bytes(b"123")
        stream = lease.open("r+b")

        def fail_unlock(open_stream: object) -> None:
            raise OSError("unlock unavailable")

        monkeypatch.setattr(git_provider_module, "_unlock_file", fail_unlock)

        git_provider_module._release_cache_lease(stream, lease)

        assert not lease.exists()

    def test_given_resolved_subdirectory_outside_checkout_then_rejects_escape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = tmp_path / "checkout"
        outside = tmp_path / "outside"
        checkout.mkdir()
        outside.mkdir()
        provider = GitSkillProvider("repo", "main", tmp_path / "cache", subdirectory="skills")
        resolve = Path.resolve

        def resolve_outside(path: Path, *args: object, **kwargs: object) -> Path:
            if path == checkout / "skills":
                return outside
            return resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve_outside)

        with pytest.raises(GitSkillProviderError, match="escapes the checkout"):
            provider._content_root(checkout)

    def test_given_symlink_in_checkout_when_sizing_then_rejects_link(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        linked_file = checkout / "linked"
        linked_file.write_text("content", encoding="utf-8")
        monkeypatch.setattr(type(linked_file), "is_symlink", lambda path: path == linked_file)

        with pytest.raises(GitSkillProviderError, match="contains a symbolic link"):
            GitSkillProvider._directory_size(checkout)

    def test_given_symlink_in_skill_tree_when_validating_then_rejects_link(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill_root = tmp_path / "skill"
        skill_root.mkdir()
        linked_file = skill_root / "linked"
        linked_file.write_text("content", encoding="utf-8")
        monkeypatch.setattr(type(linked_file), "is_symlink", lambda path: path == linked_file)

        with pytest.raises(GitSkillProviderError, match="contains a symbolic link"):
            GitSkillProvider._reject_links(skill_root)

    def test_given_lease_disappearing_during_scan_then_treats_cache_as_inactive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = GitSkillProvider("repo", "main", tmp_path)
        lease_dir = tmp_path / ".leases" / provider._cache_path.name
        lease_dir.mkdir(parents=True)
        lease_path = lease_dir / "lease"
        lease_path.write_text("1", encoding="ascii")
        path_open = Path.open

        def race_open(path: Path, *args: object, **kwargs: object):
            if path == lease_path:
                raise FileNotFoundError(path)
            return path_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", race_open)

        assert not provider._has_active_lease(provider._cache_path)

    def test_given_non_permission_eviction_error_when_removing_then_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def invoke_onerror(path: Path, *, onerror: object) -> None:
            onerror(lambda target: None, str(path), (OSError, OSError("failure"), None))

        monkeypatch.setattr(git_provider_module.shutil, "rmtree", invoke_onerror)

        with pytest.raises(OSError, match="failure"):
            GitSkillProvider._remove_cache_entry(tmp_path / "cache")

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

    def test_given_negative_total_cache_limit_when_initialized_then_raises_value_error(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="max_total_cache_bytes must be non-negative"):
            GitSkillProvider("repo", "main", tmp_path, max_total_cache_bytes=-1)

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
        snapshot = await capture_skill(registry.get_skill("incident-response"))
        assert snapshot.get_file("assets/map.bin").digest == (
            "sha256:" + hashlib.sha256(b"\x00\xff").hexdigest()
        )

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

    async def test_given_total_cache_limit_when_adding_ref_then_evicts_oldest_inactive_entry(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        source, bare, env = git_source
        _git(["branch", "copy"], cwd=source, env=env)
        _git(["push", str(bare), "copy"], cwd=source, env=env)
        cache = tmp_path / "cache"
        first = GitSkillProvider(str(bare), "main", cache)
        await first.discover()
        first_path = first._cache_path
        checkout_size = first._check_cache_size(first_path)
        (first_path / ".git" / "config").chmod(stat.S_IREAD)
        del first
        gc.collect()
        provider = GitSkillProvider(
            str(bare),
            "copy",
            cache,
            max_total_cache_bytes=checkout_size * 2 - 1,
        )

        assert await provider.discover() == ["incident-response"]

        assert not first_path.exists()
        assert provider._cache_path.is_dir()

    async def test_given_live_cache_entry_when_total_limit_reached_then_preserves_entry(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        source, bare, env = git_source
        _git(["branch", "copy"], cwd=source, env=env)
        _git(["push", str(bare), "copy"], cwd=source, env=env)
        cache = tmp_path / "cache"
        first = GitSkillProvider(str(bare), "main", cache)
        await first.discover()
        first_size = first._check_cache_size(first._cache_path)
        second = GitSkillProvider(
            str(bare), "copy", cache, max_total_cache_bytes=first_size * 2 - 1
        )

        with pytest.raises(GitSkillProviderError, match="no inactive checkout is available"):
            await second.discover()

        assert first._cache_path.is_dir()

    async def test_given_other_process_lease_when_evicting_then_preserves_then_reclaims_entry(
        self, git_source: tuple[Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        source, bare, env = git_source
        _git(["branch", "copy"], cwd=source, env=env)
        _git(["push", str(bare), "copy"], cwd=source, env=env)
        cache = tmp_path / "cache"
        initial = GitSkillProvider(str(bare), "main", cache)
        await initial.discover()
        main_path = initial._cache_path
        budget = initial._check_cache_size(main_path) * 2 - 1
        del initial
        gc.collect()
        script = "\n".join(
            [
                "import asyncio, sys",
                "from pathlib import Path",
                "from agentskills_git import GitSkillProvider",
                "async def main():",
                "    provider = GitSkillProvider(sys.argv[1], 'main', Path(sys.argv[2]))",
                "    await provider.discover()",
                "    print('ready', flush=True)",
                "    await asyncio.to_thread(sys.stdin.readline)",
                "asyncio.run(main())",
            ]
        )
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(bare), str(cache)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )
        try:
            assert process.stdout is not None
            assert process.stdout.readline().strip() == "ready"
            provider = GitSkillProvider(str(bare), "copy", cache, max_total_cache_bytes=budget)
            with pytest.raises(GitSkillProviderError, match="no inactive checkout"):
                await provider.discover()
            assert main_path.is_dir()

            process.terminate()
            process.wait(timeout=10)

            assert await provider.discover() == ["incident-response"]
            assert not main_path.exists()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)

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

        with pytest.raises(GitSkillProviderError, match="Could not fetch revision"):
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

        with pytest.raises(GitSkillProviderError, match="Could not initialize repository"):
            await provider.discover()
