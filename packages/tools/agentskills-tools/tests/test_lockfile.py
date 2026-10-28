"""Tests for Git lockfile creation and offline verification."""

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

import agentskills_tools.lockfile as lockfile_module
from agentskills_tools.cli import main
from agentskills_tools.discovery import CliError
from agentskills_tools.lockfile import (
    LockVerificationError,
    create_or_update_lock,
    source_identity,
    verify_lock,
)


def _lock_data() -> dict[str, object]:
    return {
        "lockVersion": 1,
        "source": {
            "repository": "repo",
            "ref": "main",
            "revision": "a" * 40,
            "subdirectory": ".",
        },
        "skills": [{"id": "alpha", "manifest": {}}],
    }


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
def git_checkout(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    source = tmp_path / "source"
    bare = tmp_path / "skills.git"
    checkout = tmp_path / "checkout"
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
    (skill / "guide.md").write_bytes(b"step one\x00step two")
    (source / ".gitignore").write_text("incident-response/private.md\n", encoding="utf-8")
    _git(["add", "."], cwd=source, env=env)
    _git(["commit", "-m", "first"], cwd=source, env=env)
    _git(["clone", "--bare", str(source), str(bare)], cwd=tmp_path, env=env)
    _git(["clone", str(bare), str(checkout)], cwd=tmp_path, env=env)
    return source, bare, checkout, env


class TestLockfile:
    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            ([], "unsupported or malformed lockfile version"),
            ({"lockVersion": 2}, "unsupported or malformed lockfile version"),
            ({"lockVersion": 1, "source": []}, "source must be an object"),
            (
                {"lockVersion": 1, "source": {"repository": "repo"}},
                "source must include repository and ref",
            ),
            (
                {
                    "lockVersion": 1,
                    "source": {
                        "repository": "repo",
                        "ref": "main",
                        "revision": "bad",
                        "subdirectory": ".",
                    },
                },
                "revision must be a full Git commit SHA",
            ),
            (
                {
                    "lockVersion": 1,
                    "source": {
                        "repository": "repo",
                        "ref": "main",
                        "revision": "a" * 40,
                        "subdirectory": "../outside",
                    },
                },
                "subdirectory must stay within the repository",
            ),
            ({**_lock_data(), "skills": []}, "must contain at least one skill"),
            ({**_lock_data(), "skills": [None]}, "skills must contain string IDs"),
            (
                {
                    **_lock_data(),
                    "skills": [
                        {"id": "beta", "manifest": {}},
                        {"id": "alpha", "manifest": {}},
                    ],
                },
                "IDs must be unique and sorted",
            ),
            (
                {**_lock_data(), "skills": [{"id": "alpha", "manifest": "bad"}]},
                "must contain a manifest",
            ),
        ],
    )
    def test_given_malformed_lock_when_loaded_then_raises_cli_error(
        self, tmp_path: Path, payload: object, message: str
    ) -> None:
        lockfile = tmp_path / "bad.json"
        lockfile.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(CliError, match=message):
            lockfile_module.load_lock(lockfile)

    def test_given_non_json_lock_when_loaded_then_reports_read_error(self, tmp_path: Path) -> None:
        lockfile = tmp_path / "bad.json"
        lockfile.write_text("{", encoding="utf-8")

        with pytest.raises(CliError, match="as UTF-8 JSON"):
            lockfile_module.load_lock(lockfile)

    def test_given_missing_lock_when_updated_then_reports_precondition_error(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(CliError, match="cannot update missing lockfile"):
            asyncio.run(
                create_or_update_lock(
                    "repo",
                    "main",
                    tmp_path / "missing.lock",
                    cache_dir=tmp_path / "cache",
                    update=True,
                )
            )

    def test_given_different_source_when_updating_lock_then_rejects_source_change(
        self, tmp_path: Path
    ) -> None:
        lockfile = tmp_path / "lock.json"
        lockfile.write_text(json.dumps(_lock_data()), encoding="utf-8")

        with pytest.raises(CliError, match="cannot change repository source"):
            asyncio.run(
                create_or_update_lock(
                    "other-repo",
                    "main",
                    lockfile,
                    cache_dir=tmp_path / "cache",
                    update=True,
                )
            )

    def test_given_git_source_without_skills_when_created_then_reports_empty_source(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        class EmptyProvider:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            async def discover(self) -> list[str]:
                return []

        monkeypatch.setattr(lockfile_module, "GitSkillProvider", EmptyProvider)

        with pytest.raises(CliError, match="contains no skills"):
            asyncio.run(lockfile_module.build_lock("repo", "main", cache_dir=tmp_path / "cache"))

    def test_given_provider_without_resolved_commit_when_locked_then_reports_cli_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        class UnresolvedProvider:
            resolved_commit = None

            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            async def discover(self) -> list[str]:
                return ["alpha"]

        async def capture(_skill: object) -> object:
            return object()

        monkeypatch.setattr(lockfile_module, "GitSkillProvider", UnresolvedProvider)
        monkeypatch.setattr(lockfile_module, "Skill", lambda *args: object())
        monkeypatch.setattr(lockfile_module, "capture_skill", capture)
        monkeypatch.setattr(lockfile_module, "build_skill_manifest", lambda _snapshot: {})

        with pytest.raises(CliError, match="did not resolve a commit"):
            asyncio.run(lockfile_module.build_lock("repo", "main", cache_dir=tmp_path / "cache"))

    def test_given_capture_failure_when_locking_then_wraps_as_cli_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        class Provider:
            resolved_commit = "a" * 40

            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            async def discover(self) -> list[str]:
                return ["alpha"]

        async def fail_capture(_skill: object) -> object:
            raise ValueError("bad skill")

        monkeypatch.setattr(lockfile_module, "GitSkillProvider", Provider)
        monkeypatch.setattr(lockfile_module, "Skill", lambda *args: object())
        monkeypatch.setattr(lockfile_module, "capture_skill", fail_capture)

        with pytest.raises(CliError, match=r"cannot create lock from Git source \(ValueError\)"):
            asyncio.run(lockfile_module.build_lock("repo", "main", cache_dir=tmp_path / "cache"))

    def test_given_failed_atomic_replace_when_written_then_removes_temporary_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_replace(source: Path, destination: Path) -> None:
            raise OSError("disk error")

        monkeypatch.setattr(lockfile_module.os, "replace", fail_replace)

        with pytest.raises(CliError, match="cannot write lockfile"):
            lockfile_module.write_lock(tmp_path / "lock.json", _lock_data())

        assert list(tmp_path.iterdir()) == []

    def test_given_temporary_file_creation_failure_when_written_then_reports_cli_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_tempfile(*args: object, **kwargs: object) -> None:
            raise OSError("temporary storage unavailable")

        monkeypatch.setattr(lockfile_module.tempfile, "NamedTemporaryFile", fail_tempfile)

        with pytest.raises(CliError, match="cannot write lockfile"):
            lockfile_module.write_lock(tmp_path / "lock.json", _lock_data())

    def test_given_ipv6_repository_url_when_identity_is_saved_then_keeps_port(self):
        assert source_identity("https://user:token@[2001:db8::1]:8443/org/repo.git?key=x") == (
            "https://[2001:db8::1]:8443/org/repo.git"
        )

    def test_given_invalid_repository_port_when_lock_created_then_fails_before_git(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(CliError, match="invalid Git repository URL"):
            asyncio.run(
                create_or_update_lock(
                    "https://example.com:not-a-port/repo.git",
                    "main",
                    tmp_path / "lock.json",
                    cache_dir=tmp_path / "cache",
                )
            )

        assert not (tmp_path / "cache").exists()

    def test_given_invalid_origin_when_looking_up_git_value_then_raises_lock_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_git(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            raise OSError("git unavailable")

        monkeypatch.setattr(lockfile_module.subprocess, "run", fail_git)

        with pytest.raises(LockVerificationError, match="local Git repository"):
            lockfile_module._git_output(tmp_path, "remote", "get-url", "origin")

        with pytest.raises(LockVerificationError, match="locked Git objects"):
            lockfile_module._git_bytes(tmp_path, "show", "HEAD:SKILL.md")

    @pytest.mark.parametrize(
        "tree_record",
        [b"120000 blob object\talpha/link\0", b"160000 commit object\talpha/submodule\0"],
    )
    def test_given_link_or_submodule_in_git_tree_when_listing_then_rejects_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tree_record: bytes
    ) -> None:
        monkeypatch.setattr(lockfile_module, "_git_bytes", lambda *args: tree_record)

        with pytest.raises(LockVerificationError, match="symbolic link or submodule"):
            lockfile_module._committed_skill_files(tmp_path, "a" * 40, ".")

    def test_given_git_tree_path_outside_subdirectory_when_listed_then_ignores_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            lockfile_module,
            "_git_bytes",
            lambda *args: b"100644 blob object\tother/alpha/SKILL.md\0",
        )

        assert lockfile_module._committed_skill_files(tmp_path, "a" * 40, "skills") == {}

    def test_given_credentialed_url_when_identity_is_saved_then_credentials_are_removed(self):
        assert source_identity("https://token:secret@github.com/org/repo.git?sig=private") == (
            "https://github.com/org/repo.git"
        )

    def test_given_scp_git_url_when_identity_is_saved_then_user_is_removed(self):
        assert source_identity("git@github.com:org/repo.git") == "ssh://github.com/org/repo.git"

    def test_given_scp_url_without_user_when_identity_is_saved_then_adds_ssh_scheme(self):
        assert source_identity("github.com:org/repo.git") == "ssh://github.com/org/repo.git"

    def test_given_existing_lock_when_creating_then_refuses_overwrite(
        self, git_checkout: tuple[Path, Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        _, bare, _, _ = git_checkout
        lockfile = tmp_path / "agentskills.lock.json"
        lockfile.write_text("existing", encoding="utf-8")

        with pytest.raises(CliError, match="already exists"):
            asyncio.run(
                create_or_update_lock(
                    str(bare),
                    "main",
                    lockfile,
                    cache_dir=tmp_path / "cache",
                )
            )

    def test_given_lockfile_when_created_then_records_revision_and_file_digests(
        self, git_checkout: tuple[Path, Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        _, bare, _, _ = git_checkout
        lockfile = tmp_path / "agentskills.lock.json"

        lock = asyncio.run(
            create_or_update_lock(str(bare), "main", lockfile, cache_dir=tmp_path / "cache")
        )

        saved = json.loads(lockfile.read_text(encoding="utf-8"))
        assert saved == lock
        assert lock["lockVersion"] == 1
        assert lock["source"]["repository"] == bare.as_posix()
        assert len(lock["source"]["revision"]) in {40, 64}
        resources = lock["skills"][0]["manifest"]["resources"]
        assert any(
            resource["digest"].startswith("sha256:")
            and resource["size"] == len(b"step one\x00step two")
            for resource in resources
        )

    def test_given_existing_source_lock_when_updated_then_resolves_new_ref(
        self, git_checkout: tuple[Path, Path, Path, dict[str, str]], tmp_path: Path
    ) -> None:
        source, bare, _, env = git_checkout
        lockfile = tmp_path / "agentskills.lock.json"
        first = asyncio.run(
            create_or_update_lock(str(bare), "main", lockfile, cache_dir=tmp_path / "cache")
        )
        (source / "incident-response" / "guide.md").write_bytes(b"updated source")
        _git(["add", "."], cwd=source, env=env)
        _git(["commit", "-m", "update locked source"], cwd=source, env=env)
        _git(["push", str(bare), "main"], cwd=source, env=env)

        updated = asyncio.run(
            create_or_update_lock(
                str(bare),
                "main",
                lockfile,
                cache_dir=tmp_path / "cache",
                update=True,
            )
        )

        assert updated["source"]["revision"] != first["source"]["revision"]
        resources = updated["skills"][0]["manifest"]["resources"]
        assert any(resource["size"] == len(b"updated source") for resource in resources)
        assert json.loads(lockfile.read_text(encoding="utf-8")) == updated

    def test_given_offline_checkout_when_verified_then_never_fetches(
        self,
        git_checkout: tuple[Path, Path, Path, dict[str, str]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, bare, checkout, _ = git_checkout
        lockfile = tmp_path / "agentskills.lock.json"
        asyncio.run(
            create_or_update_lock(str(bare), "main", lockfile, cache_dir=tmp_path / "cache")
        )
        original_run = subprocess.run
        git_calls: list[list[str]] = []

        def no_network(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            git_calls.append(command)
            assert "fetch" not in command and "clone" not in command
            return original_run(command, **kwargs)

        monkeypatch.setattr("agentskills_tools.lockfile.subprocess.run", no_network)

        count = asyncio.run(verify_lock(lockfile, checkout))

        assert count == 1
        assert git_calls

    def test_given_changed_file_when_verified_then_reports_drift(
        self,
        git_checkout: tuple[Path, Path, Path, dict[str, str]],
        tmp_path: Path,
    ) -> None:
        _, bare, checkout, env = git_checkout
        lockfile = tmp_path / "agentskills.lock.json"
        asyncio.run(
            create_or_update_lock(str(bare), "main", lockfile, cache_dir=tmp_path / "cache")
        )
        (checkout / "incident-response" / "guide.md").write_bytes(b"changed")
        _git(["add", "."], cwd=checkout, env=env)
        _git(["commit", "-m", "change locked skill"], cwd=checkout, env=env)

        with pytest.raises(LockVerificationError, match="revision differs from lockfile"):
            asyncio.run(verify_lock(lockfile, checkout))

    def test_given_uncommitted_change_when_verified_then_rejects_working_tree(
        self,
        git_checkout: tuple[Path, Path, Path, dict[str, str]],
        tmp_path: Path,
    ) -> None:
        _, bare, checkout, _ = git_checkout
        lockfile = tmp_path / "agentskills.lock.json"
        asyncio.run(
            create_or_update_lock(str(bare), "main", lockfile, cache_dir=tmp_path / "cache")
        )
        (checkout / "incident-response" / "guide.md").write_bytes(b"changed")

        with pytest.raises(LockVerificationError, match="local changes"):
            asyncio.run(verify_lock(lockfile, checkout))

    def test_given_ignored_file_when_verified_then_rejects_file_inventory_drift(
        self,
        git_checkout: tuple[Path, Path, Path, dict[str, str]],
        tmp_path: Path,
    ) -> None:
        _, bare, checkout, _ = git_checkout
        lockfile = tmp_path / "agentskills.lock.json"
        asyncio.run(
            create_or_update_lock(str(bare), "main", lockfile, cache_dir=tmp_path / "cache")
        )
        (checkout / "incident-response" / "private.md").write_text("local only", encoding="utf-8")

        with pytest.raises(LockVerificationError, match="file set differs"):
            asyncio.run(verify_lock(lockfile, checkout))

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ("origin", "origin does not match"),
            ("subdirectory", "subdirectory is missing"),
            ("skill-set", "skill set differs"),
            ("manifest", "differs from lockfile"),
        ],
    )
    def test_given_modified_lock_when_verified_then_reports_mismatch(
        self,
        git_checkout: tuple[Path, Path, Path, dict[str, str]],
        tmp_path: Path,
        change: str,
        message: str,
    ) -> None:
        _, bare, checkout, _ = git_checkout
        lockfile = tmp_path / "agentskills.lock.json"
        lock = asyncio.run(
            create_or_update_lock(str(bare), "main", lockfile, cache_dir=tmp_path / "cache")
        )
        if change == "origin":
            lock["source"]["repository"] = "https://different.example/skills.git"
        elif change == "subdirectory":
            lock["source"]["subdirectory"] = "missing"
        elif change == "skill-set":
            lock["skills"].append({"id": "ghost", "manifest": {}})
            lock["skills"].sort(key=lambda entry: entry["id"])
        else:
            lock["skills"][0]["manifest"]["resources"][0]["digest"] = "sha256:" + "0" * 64
        lockfile_module.write_lock(lockfile, lock)

        with pytest.raises(LockVerificationError, match=message):
            asyncio.run(verify_lock(lockfile, checkout))

    def test_given_non_git_checkout_when_verified_then_reports_repository_error(
        self, tmp_path: Path
    ) -> None:
        lockfile = tmp_path / "lock.json"
        lockfile_module.write_lock(lockfile, _lock_data())

        with pytest.raises(LockVerificationError, match="local Git repository"):
            asyncio.run(verify_lock(lockfile, tmp_path))

    def test_given_cli_lock_then_verify_when_checkout_matches_then_succeeds(
        self,
        git_checkout: tuple[Path, Path, Path, dict[str, str]],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _, bare, checkout, _ = git_checkout
        lockfile = tmp_path / "agentskills.lock.json"
        cache = tmp_path / "cache"

        assert (
            main(
                [
                    "lock",
                    "create",
                    str(bare),
                    "--ref",
                    "main",
                    "--lockfile",
                    str(lockfile),
                    "--cache-dir",
                    str(cache),
                ]
            )
            == 0
        )
        created = capsys.readouterr().out
        assert "Created lock for 1 skill" in created
        assert main(["lock", "verify", str(lockfile), "--checkout", str(checkout)]) == 0
        assert "Verified 1 skill against" in capsys.readouterr().out

    def test_given_drift_when_cli_verifies_then_exits_findings(
        self,
        git_checkout: tuple[Path, Path, Path, dict[str, str]],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _, bare, checkout, env = git_checkout
        lockfile = tmp_path / "agentskills.lock.json"
        asyncio.run(
            create_or_update_lock(str(bare), "main", lockfile, cache_dir=tmp_path / "cache")
        )
        (checkout / "incident-response" / "guide.md").write_bytes(b"changed")
        _git(["add", "."], cwd=checkout, env=env)
        _git(["commit", "-m", "change locked skill"], cwd=checkout, env=env)

        assert main(["lock", "verify", str(lockfile), "--checkout", str(checkout)]) == 1
        assert "lock verification failed" in capsys.readouterr().err
