"""Check that every package agrees on its version, and matches the release tag.

Run before tagging a release::

    python scripts/check_release_version.py            # the six packages agree
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

PACKAGES = [
    "packages/core/agentskills-core",
    "packages/providers/agentskills-fs",
    "packages/providers/agentskills-http",
    "packages/integrations/agentskills-langchain",
    "packages/integrations/agentskills-agentframework",
    "packages/integrations/agentskills-mcp-server",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="release tag, e.g. v0.3.0")
    args = parser.parse_args()

    versions: dict[str, str] = {}
    for package in PACKAGES:
        manifest = ROOT / package / "pyproject.toml"
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        versions[Path(package).name] = data["tool"]["poetry"]["version"]

    for name, version in versions.items():
        print(f"  {name:<32} {version}")

    distinct = set(versions.values())
    if len(distinct) > 1:
        print(
            f"\nERROR: packages disagree on the version: {sorted(distinct)}.\n"
            "Run scripts/bump-version.ps1 (or .sh) to set them together.",
            file=sys.stderr,
        )
        return 1

    version = distinct.pop()
    if args.tag is not None and args.tag != f"v{version}":
        print(
            f"\nERROR: tag {args.tag} does not match the packaged version {version}.\n"
            f"Either the version bump was missed, or the tag should be v{version}.",
            file=sys.stderr,
        )
        return 1

    print(f"\nOK: all six packages at {version}" + (f", matching {args.tag}" if args.tag else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
