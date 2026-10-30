"""Build distributions and smoke-test installed commands in an isolated environment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import venv
from configparser import ConfigParser
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile

from check_release_version import PACKAGES, ROOT


def create_parser() -> argparse.ArgumentParser:
    """Create the build-and-install smoke-check parser."""
    return argparse.ArgumentParser(description=__doc__)


def _run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    print(f"Running: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=600)


def _verify_wheel(wheel: Path, manifest: dict, version: str) -> None:
    with ZipFile(wheel) as archive:
        metadata_path = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = BytesParser().parsebytes(archive.read(metadata_path))
        if metadata["Name"] != manifest["name"] or metadata["Version"] != version:
            raise ValueError(f"Artifact identity or version mismatch: {wheel.name}")
        namespace = manifest["packages"][0]["include"]
        if f"{namespace}/py.typed" not in archive.namelist():
            raise ValueError(f"Typing marker missing: {wheel.name}")
        if manifest["name"] == "agentskills-mcp-extension":
            entry_path = next(
                name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")
            )
            entries = ConfigParser()
            entries.read_string(archive.read(entry_path).decode("utf-8"))
            expected = {"agentskills-mcp": "agentskills_mcp_extension.__main__:main"}
            if dict(entries["console_scripts"]) != expected:
                raise ValueError("The MCP wheel must expose only the short agentskills-mcp command")
            if any(name.startswith("agentskills_mcp_server/") for name in archive.namelist()):
                raise ValueError("Legacy MCP namespace found in the wheel")


def _check_artifacts(work: Path) -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"][
        "poetry"
    ]["version"]
    env = os.environ.copy()
    env["POETRY_VIRTUALENVS_CREATE"] = "false"
    wheels: list[Path] = []
    for package in PACKAGES:
        directory = ROOT / package
        manifest = tomllib.loads((directory / "pyproject.toml").read_text(encoding="utf-8"))[
            "tool"
        ]["poetry"]
        output = work / "dist" / manifest["name"]
        _run(["poetry", "-C", str(directory), "build", "-o", str(output)], ROOT, env)
        built = list(output.glob("*.whl"))
        if len(built) != 1 or len(list(output.glob("*.tar.gz"))) != 1:
            raise ValueError(f"Expected exactly one wheel and sdist for {package}")
        _verify_wheel(built[0], manifest, version)
        wheels.extend(built)

    environment = work / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    installed_env = os.environ.copy()
    installed_env.pop("PYTHONPATH", None)
    installed_env.pop("PYTHONHOME", None)
    installed_env["VIRTUAL_ENV"] = str(environment)
    installed_env["PATH"] = str(scripts) + os.pathsep + installed_env.get("PATH", "")
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--progress-bar",
            "off",
            "--disable-pip-version-check",
            *map(str, wheels),
        ],
        work,
        installed_env,
    )
    _run([str(python), "-m", "pip", "check"], work, installed_env)
    _run(
        [
            str(python),
            "-c",
            "import importlib.util; from pathlib import Path; "
            "import agentskills_mcp_extension; "
            "assert Path(agentskills_mcp_extension.__file__).is_relative_to(Path.cwd()); "
            "assert importlib.util.find_spec('agentskills_mcp_server') is None",
        ],
        work,
        installed_env,
    )
    config = work / "server.json"
    config.write_text(
        json.dumps(
            {
                "name": "Installed wheel smoke",
                "skills": [
                    {
                        "id": "incident-response",
                        "provider": "fs",
                        "options": {"root": str(ROOT / "examples/skills")},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    suffix = ".exe" if os.name == "nt" else ""
    mcp = scripts / f"agentskills-mcp{suffix}"
    tools = scripts / f"agentskills{suffix}"
    help_result = subprocess.run(
        [str(mcp), "--help"],
        cwd=work,
        env=installed_env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    if "usage: agentskills-mcp " not in help_result.stdout:
        raise ValueError("Installed MCP help does not advertise the short command")
    _run([str(mcp), "--config", str(config), "--check"], work, installed_env)
    _run(
        [str(python), "-m", "agentskills_mcp_extension", "--config", str(config), "--check"],
        work,
        installed_env,
    )
    _run([str(tools), "serve", str(ROOT / "examples/skills"), "--check"], work, installed_env)
    print(f"Verified {len(wheels)} wheel/sdist pairs and isolated installed commands.")


def main() -> int:
    """Build and validate artifacts without publishing or modifying project environments."""
    create_parser().parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="agentskills-artifacts-") as temporary:
            _check_artifacts(Path(temporary))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Artifact smoke check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
