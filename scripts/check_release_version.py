"""Check that every package agrees on its version, and matches the release tag.

Run before tagging a release::

    python scripts/check_release_version.py            # every package agrees
    python scripts/check_release_version.py --tag v0.3.0   # ...and match the tag

The tag must be ``v`` followed by the exact version string, so ``0.3.0rc1`` is
tagged ``v0.3.0rc1``. Comparing strings rather than parsed versions keeps the
tag, the distribution filename, and the PyPI page spelled identically.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent

CORE = "packages/core/agentskills-core"

DEPENDENTS = [
    "packages/adapters/agentskills-adapters",
    "packages/providers/agentskills-fs",
    "packages/providers/agentskills-http",
    "packages/integrations/agentskills-langchain",
    "packages/integrations/agentskills-agentframework",
    "packages/integrations/agentskills-mcp-server",
    "packages/cli/agentskills-cli",
    "packages/testing/agentskills-testing",
]

PACKAGES = [CORE, *DEPENDENTS]


def _manifest(package: str) -> dict:
    return tomllib.loads((ROOT / package / "pyproject.toml").read_text(encoding="utf-8"))


def _check_versions(tag: str | None) -> tuple[str | None, list[str]]:
    """Every package, and the workspace root, must carry the same version."""
    versions = {Path(p).name: _manifest(p)["tool"]["poetry"]["version"] for p in PACKAGES}
    versions["(workspace root)"] = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["tool"]["poetry"]["version"]

    for name, version in versions.items():
        print(f"  {name:<32} {version}")

    distinct = set(versions.values())
    if len(distinct) > 1:
        return None, [
            f"packages disagree on the version: {sorted(distinct)}. "
            "Run scripts/bump-version.ps1 (or .sh) to set them together."
        ]

    version = distinct.pop()
    if tag is not None and tag != f"v{version}":
        return version, [
            f"tag {tag} does not match the packaged version {version}. "
            f"Either the version bump was missed, or the tag should be v{version}."
        ]
    return version, []


def _check_core_floor(version: str) -> list[str]:
    """Dependents must require the core they are released with.

    They ship in lockstep, so a floor below the release version lets pip
    resolve an older core against a newer dependent and fail at import.
    """
    expected = f">={version},<1.0"
    errors = []
    print()
    for package in DEPENDENTS:
        found = _manifest(package)["tool"]["poetry"]["dependencies"]["agentskills-core"]
        print(f"  {Path(package).name:<32} agentskills-core {found}")
        if found != expected:
            errors.append(
                f"{Path(package).name} requires agentskills-core {found!r}, expected {expected!r}."
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="release tag, e.g. v0.3.0")
    args = parser.parse_args()

    version, errors = _check_versions(args.tag)
    if version is not None:
        errors += _check_core_floor(version)

    if errors:
        print("\nERROR:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        f"\nOK: all {len(PACKAGES)} packages at {version}"
        + (f", matching {args.tag}" if args.tag else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
