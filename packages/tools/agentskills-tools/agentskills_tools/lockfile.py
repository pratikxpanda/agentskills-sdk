"""Create and verify commit-pinned Agent Skills lockfiles."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from agentskills_core import (
    AgentSkillsError,
    Skill,
    SkillFile,
    SkillSnapshot,
    build_skill_manifest,
    capture_skill,
)
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_git import GitSkillProvider
from agentskills_git.provider import GitSkillProviderError
from agentskills_tools.discovery import CliError

LOCK_SCHEMA_VERSION = 1
_CACHE_ROOT = Path(
    os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    if os.name == "nt"
    else os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
)
DEFAULT_GIT_CACHE_DIR = _CACHE_ROOT / "agentskills" / "git"
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_SCP_URL_PATTERN = re.compile(r"^(?:[^@/:]+@)?([^:/]+):(.+)$")


class LockVerificationError(ValueError):
    """Raised when a checkout does not match its lockfile."""


def source_identity(repository: str) -> str:
    """Return a repository identity without embedded credentials or query data.

    Args:
        repository: Git URL, SCP-style SSH URL, or local repository path.

    Returns:
        A normalized identity suitable for storing in a lockfile.
    """
    if "://" in repository:
        parsed = urlsplit(repository)
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    if not re.match(r"^[A-Za-z]:[\\/]", repository):
        scp_match = _SCP_URL_PATTERN.fullmatch(repository)
        if scp_match:
            return f"ssh://{scp_match.group(1)}/{scp_match.group(2)}"
    return Path(repository).expanduser().resolve().as_posix()


async def build_lock(
    repository: str,
    ref: str,
    *,
    cache_dir: Path,
    subdirectory: str = ".",
) -> dict[str, Any]:
    """Resolve a Git source and capture every published skill manifest.

    Args:
        repository: Git URL or local repository path.
        ref: Branch, tag, or commit to resolve.
        cache_dir: Cache directory used by the Git provider.
        subdirectory: POSIX relative path containing the skill directories.

    Returns:
        JSON-compatible lockfile data.

    Raises:
        CliError: If the repository contains no skills or cannot be captured.
    """
    try:
        repository_identity = source_identity(repository)
        provider = GitSkillProvider(
            repository,
            ref,
            cache_dir,
            subdirectory=subdirectory,
            refresh=True,
        )
        skill_ids = await provider.discover()
        if not skill_ids:
            raise CliError("Git source contains no skills")
        skills = []
        for skill_id in skill_ids:
            snapshot = await capture_skill(Skill(skill_id, provider))
            skills.append({"id": skill_id, "manifest": build_skill_manifest(snapshot)})
        commit = provider.resolved_commit
        if commit is None:
            raise CliError("Git provider did not resolve a commit")
    except CliError:
        raise
    except (AgentSkillsError, GitSkillProviderError, OSError, ValueError) as exc:
        raise CliError(f"cannot create lock from Git source ({type(exc).__name__})") from exc
    return {
        "lockVersion": LOCK_SCHEMA_VERSION,
        "source": {
            "repository": repository_identity,
            "ref": ref,
            "revision": commit,
            "subdirectory": PurePosixPath(subdirectory).as_posix(),
        },
        "skills": skills,
    }


def write_lock(lock_path: Path, lock: dict[str, Any]) -> None:
    """Write a lockfile atomically with stable JSON formatting.

    Args:
        lock_path: Destination path.
        lock: Lockfile mapping returned by :func:`build_lock`.
    """
    lock_path = lock_path.expanduser()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=lock_path.parent,
            prefix=f".{lock_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(lock, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_path, lock_path)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise CliError(f"cannot write lockfile '{lock_path.name}' ({type(exc).__name__})") from None


def load_lock(lock_path: Path) -> dict[str, Any]:
    """Load and validate the lockfile's structural contract.

    Args:
        lock_path: Lockfile path.

    Returns:
        Parsed lock data.

    Raises:
        CliError: If the file is unreadable or has an unsupported structure.
    """
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise CliError(f"cannot read lockfile '{lock_path}' as UTF-8 JSON") from None
    if not isinstance(lock, dict) or lock.get("lockVersion") != LOCK_SCHEMA_VERSION:
        raise CliError("unsupported or malformed lockfile version")
    source = lock.get("source")
    if not isinstance(source, dict):
        raise CliError("lockfile source must be an object")
    if not all(isinstance(source.get(key), str) and source[key] for key in ("repository", "ref")):
        raise CliError("lockfile source must include repository and ref")
    revision = source.get("revision")
    if not isinstance(revision, str) or not _COMMIT_PATTERN.fullmatch(revision):
        raise CliError("lockfile source revision must be a full Git commit SHA")
    subdirectory = source.get("subdirectory")
    if (
        not isinstance(subdirectory, str)
        or "\\" in subdirectory
        or "\x00" in subdirectory
        or PurePosixPath(subdirectory).is_absolute()
        or ".." in PurePosixPath(subdirectory).parts
    ):
        raise CliError("lockfile source subdirectory must stay within the repository")
    skills = lock.get("skills")
    if not isinstance(skills, list) or not skills:
        raise CliError("lockfile must contain at least one skill")
    ids = [entry.get("id") for entry in skills if isinstance(entry, dict)]
    if len(ids) != len(skills) or not all(isinstance(skill_id, str) for skill_id in ids):
        raise CliError("lockfile skills must contain string IDs")
    if ids != sorted(set(ids)):
        raise CliError("lockfile skill IDs must be unique and sorted")
    if any(not isinstance(entry.get("manifest"), dict) for entry in skills):
        raise CliError("each lockfile skill must contain a manifest")
    return lock


def _git_output(checkout: Path, *args: str, isolated_config: bool = True) -> str:
    env = os.environ.copy()
    if isolated_config:
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_GLOBAL"] = os.devnull
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), *args],
            capture_output=True,
            check=True,
            env=env,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        raise LockVerificationError("checkout is not a readable local Git repository") from None
    return result.stdout.strip()


def _git_bytes(checkout: Path, *args: str) -> bytes:
    env = os.environ.copy()
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), *args],
            capture_output=True,
            check=True,
            env=env,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        raise LockVerificationError(
            "cannot read locked Git objects from the local checkout"
        ) from None
    return result.stdout


def _committed_skill_files(
    checkout: Path, revision: str, subdirectory: str
) -> dict[str, list[str]]:
    tree_path = "." if subdirectory == "." else subdirectory
    output = _git_bytes(checkout, "ls-tree", "-r", "-z", revision, "--", tree_path)
    prefix = "" if subdirectory == "." else f"{subdirectory.rstrip('/')}/"
    by_skill: dict[str, list[str]] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_type, _ = metadata.decode("ascii").split()
        if mode == "120000" or object_type == "commit":
            raise LockVerificationError("locked Git tree contains a symbolic link or submodule")
        path = os.fsdecode(raw_path)
        if not path.startswith(prefix):
            continue
        relative = path[len(prefix) :]
        parts = relative.split("/")
        if len(parts) < 2 or parts[0].startswith("."):
            continue
        by_skill.setdefault(parts[0], []).append("/".join(parts[1:]))
    return {skill_id: sorted(paths) for skill_id, paths in by_skill.items() if "SKILL.md" in paths}


async def verify_lock(lock_path: Path, checkout: Path) -> int:
    """Verify a local checkout against a lockfile without network access.

    Args:
        lock_path: Lockfile to verify.
        checkout: Existing local Git working tree at the locked revision.

    Returns:
        Number of verified skills.

    Raises:
        CliError: If the lockfile cannot be read or is malformed.
        LockVerificationError: If repository, revision, or skill content differs.
    """
    lock = load_lock(lock_path)
    checkout = checkout.expanduser().resolve()
    source = lock["source"]
    try:
        actual_origin = source_identity(_git_output(checkout, "remote", "get-url", "origin"))
    except LockVerificationError:
        raise
    if actual_origin != source["repository"]:
        raise LockVerificationError("checkout origin does not match the lockfile source")
    revision = _git_output(checkout, "rev-parse", "HEAD")
    if revision != source["revision"]:
        raise LockVerificationError(
            "checkout revision differs from lockfile "
            f"({revision[:12]} != {source['revision'][:12]})"
        )
    if _git_output(
        checkout,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        source["subdirectory"],
        isolated_config=False,
    ):
        raise LockVerificationError("checkout has local changes in the locked subdirectory")
    content_root = checkout.joinpath(*PurePosixPath(source["subdirectory"]).parts).resolve()
    if not content_root.is_relative_to(checkout) or not content_root.is_dir():
        raise LockVerificationError("locked subdirectory is missing or escapes the checkout")
    provider = LocalFileSystemSkillProvider(content_root)
    actual_ids = await provider.discover()
    expected_skills = {entry["id"]: entry["manifest"] for entry in lock["skills"]}
    committed_files = _committed_skill_files(checkout, revision, source["subdirectory"])
    if actual_ids != sorted(expected_skills) or set(committed_files) != set(expected_skills):
        raise LockVerificationError("checkout skill set differs from lockfile")
    for skill_id, expected_manifest in expected_skills.items():
        if await provider.list_files(skill_id) != committed_files[skill_id]:
            raise LockVerificationError(f"skill '{skill_id}' file set differs from locked commit")
        files = []
        for path in committed_files[skill_id]:
            repo_path = "/".join(
                part for part in (source["subdirectory"], skill_id, path) if part != "."
            )
            data = _git_bytes(checkout, "show", f"{revision}:{repo_path}")
            files.append(SkillFile(path, data))
        snapshot = SkillSnapshot(skill_id, tuple(files))
        actual_manifest = build_skill_manifest(snapshot)
        if actual_manifest != expected_manifest:
            raise LockVerificationError(f"skill '{skill_id}' differs from lockfile")
    return len(expected_skills)


async def create_or_update_lock(
    repository: str,
    ref: str,
    lock_path: Path,
    *,
    cache_dir: Path,
    subdirectory: str = ".",
    update: bool = False,
) -> dict[str, Any]:
    """Create a lockfile or explicitly update an existing source lock.

    Args:
        repository: Git URL or local repository path.
        ref: Branch, tag, or commit to resolve.
        lock_path: Lockfile destination.
        cache_dir: Git provider cache directory.
        subdirectory: POSIX relative path containing skills.
        update: Require an existing lock from the same source identity.

    Returns:
        The written lock mapping.

    Raises:
        CliError: If create/update preconditions fail or the source cannot be captured.
    """
    lock_path = lock_path.expanduser()
    try:
        identity = source_identity(repository)
    except ValueError:
        raise CliError("invalid Git repository URL or path") from None
    if update:
        if not lock_path.is_file():
            raise CliError(f"cannot update missing lockfile '{lock_path}'")
        previous = load_lock(lock_path)
        if previous["source"]["repository"] != identity:
            raise CliError("lock update cannot change repository source")
    elif lock_path.exists():
        raise CliError(f"lockfile already exists: {lock_path}")

    lock = await build_lock(
        repository,
        ref,
        cache_dir=cache_dir,
        subdirectory=subdirectory,
    )
    write_lock(lock_path, lock)
    return lock
