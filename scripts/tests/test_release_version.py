"""Regression checks for lockstep sibling dependency policy."""

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from scripts import check_release_version as release


@pytest.mark.parametrize(
    ("requirement", "valid"),
    [(">=0.9.0,<0.10.0", True), (">=0.9.0,<1.0", False)],
)
def test_given_pre_one_sibling_when_checked_then_requires_same_minor(
    monkeypatch, requirement, valid
):
    manifest = {"tool": {"poetry": {"dependencies": {"agentskills-core": requirement}}}}
    monkeypatch.setattr(release, "DEPENDENTS", ["example"])
    monkeypatch.setattr(release, "_manifest", lambda package: manifest)

    errors = release._check_sibling_floors("0.9.0")

    assert (not errors) is valid


@pytest.mark.parametrize(
    ("version", "requirement"),
    [
        ("0.9.2", ">=0.9.2,<0.10.0"),
        ("0.10.0", ">=0.10.0,<0.11.0"),
        ("0.9.0rc1", ">=0.9.0rc1,<0.10.0"),
        ("1.2.3", ">=1.2.3,<2.0.0"),
    ],
)
def test_given_release_family_when_checked_then_uses_correct_ceiling(
    monkeypatch, version, requirement
):
    manifest = {"tool": {"poetry": {"dependencies": {"agentskills-core": requirement}}}}
    monkeypatch.setattr(release, "DEPENDENTS", ["example"])
    monkeypatch.setattr(release, "_manifest", lambda package: manifest)

    assert release._check_sibling_floors(version) == []


@pytest.mark.parametrize("shell", ["powershell", "bash"])
@pytest.mark.parametrize(
    ("version", "requirement"),
    [("0.9.0", ">=0.9.0,<0.10.0"), ("0.10.0", ">=0.10.0,<0.11.0"), ("1.0.0", ">=1.0.0,<2.0.0")],
)
def test_given_version_bump_when_script_runs_then_versions_and_ranges_agree(
    tmp_path, monkeypatch, shell, version, requirement
):
    manifests = ["pyproject.toml", *(f"{package}/pyproject.toml" for package in release.PACKAGES)]
    for relative in manifests:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = (release.ROOT / relative).read_text(encoding="utf-8-sig")
        current = tomllib.loads(content)["tool"]["poetry"]["version"]
        target.write_text(
            content.replace(f'version = "{current}"', 'version = "0.8.0"'), encoding="utf-8"
        )
    script_name = "bump-version.ps1" if shell == "powershell" else "bump-version.sh"
    script = tmp_path / "scripts" / script_name
    script.parent.mkdir()
    shutil.copy2(release.ROOT / "scripts" / script_name, script)
    if shell == "powershell":
        executable = shutil.which("pwsh")
        arguments = ["-NoProfile", "-NonInteractive", "-File", str(script), "-Version", version]
    else:
        git = shutil.which("git")
        executable = (
            str(Path(git).parent.parent / "bin" / "bash.exe")
            if os.name == "nt" and git
            else shutil.which("bash")
        )
        arguments = [str(script), "--version", version]
    if not executable or not shutil.which(executable):
        pytest.skip(f"{shell} is not available")

    subprocess.run([executable, *arguments], cwd=tmp_path, check=True, capture_output=True)

    for relative in manifests:
        manifest = tomllib.loads((tmp_path / relative).read_text(encoding="utf-8-sig"))
        assert manifest["tool"]["poetry"]["version"] == version
        for name, spec in manifest["tool"]["poetry"]["dependencies"].items():
            if name.startswith("agentskills-") and not (isinstance(spec, dict) and "path" in spec):
                assert (spec["version"] if isinstance(spec, dict) else spec) == requirement
    monkeypatch.setattr(release, "ROOT", tmp_path)
    assert release._check_sibling_floors(version) == []
