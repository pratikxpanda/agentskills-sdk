"""Check that every package declares the third-party modules it imports.

Run it like the other release checks::

    python scripts/check_declared_dependencies.py

A missing declaration is invisible in this repo, because every package is
installed into one shared virtualenv alongside its siblings. It only appears
for somebody who installed a single package from PyPI, and it appears as an
ImportError on their first command. ``agentskills-cli`` shipped that way for a
whole milestone: it imports ``yaml`` and never declared ``pyyaml``, riding on
the copy that ``agentskills-core`` pulled in.

Only module-level imports count. An import nested in a function or guarded by
``except ImportError`` is an optional capability, which is exactly the pattern
used for tokenizers and for cross-integration bridges, and declaring those
would defeat the point of making them optional.
"""

from __future__ import annotations

import argparse
import ast
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).parent.parent

PACKAGES = [
    "packages/core/agentskills-core",
    "packages/adapters/agentskills-adapters",
    "packages/providers/agentskills-fs",
    "packages/providers/agentskills-http",
    "packages/integrations/agentskills-langchain",
    "packages/integrations/agentskills-agentframework",
    "packages/integrations/agentskills-mcp-server",
    "packages/cli/agentskills-cli",
    "packages/testing/agentskills-testing",
]

OPTIONAL_ERRORS = {"ImportError", "ModuleNotFoundError"}


def _normalise(name: str) -> str:
    """PEP 503 name comparison, so pyyaml and PyYAML are one dependency."""
    out = []
    previous_separator = False
    for char in name.lower():
        if char in "-_.":
            if not previous_separator:
                out.append("-")
            previous_separator = True
        else:
            out.append(char)
            previous_separator = False
    return "".join(out)


def _guards_import(node: ast.Try) -> bool:
    for handler in node.handlers:
        caught = handler.type
        if isinstance(caught, ast.Tuple):
            names = {name.id for name in caught.elts if isinstance(name, ast.Name)}
        elif isinstance(caught, ast.Name):
            names = {caught.id}
        else:
            continue
        if names & OPTIONAL_ERRORS:
            return True
    return False


def _required_imports(body: list[ast.stmt]) -> set[str]:
    """Top-level module names imported unconditionally.

    Descends into ``if`` and unguarded ``try`` blocks — a ``TYPE_CHECKING``
    import still names a package the type checker has to find — but stops at
    a function or class, and at any ``try`` that catches an import failure.
    """
    modules: set[str] = set()
    for node in body:
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
        elif isinstance(node, ast.Try):
            if not _guards_import(node):
                modules |= _required_imports(node.body)
        elif isinstance(node, ast.If):
            modules |= _required_imports(node.body) | _required_imports(node.orelse)
    return modules


def _source_imports(package: Path) -> set[str]:
    modules: set[str] = set()
    for path in sorted(package.rglob("agentskills_*/**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules |= _required_imports(tree.body)
    return modules


def _distributions_for(module: str, index: dict[str, list[str]]) -> set[str]:
    """Which distribution ships this module, normalised.

    Falls back to the module name itself, which is right often enough to give
    a usable error message when the module is not installed here at all.
    """
    return {_normalise(name) for name in index.get(module, [module])}


def _declared(package: Path) -> set[str]:
    manifest = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = manifest["tool"]["poetry"]["dependencies"]
    return {_normalise(name) for name in dependencies if name != "python"}


def _check(package: str, index: dict[str, list[str]]) -> list[str]:
    path = ROOT / package
    declared = _declared(path)
    stdlib = sys.stdlib_module_names

    missing = []
    for module in sorted(_source_imports(path)):
        if module in stdlib or module == path.name.replace("-", "_"):
            continue
        candidates = _distributions_for(module, index)
        if not candidates & declared:
            missing.append(f"{module} (from {', '.join(sorted(candidates))})")

    print(f"  {path.name:<32} {len(declared)} declared, {len(missing)} missing")
    return [
        f"{path.name} imports {module} without declaring it in pyproject.toml."
        for module in missing
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    index = packages_distributions()
    errors: list[str] = []
    for package in PACKAGES:
        errors += _check(package, index)

    if errors:
        print("\nERROR:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"\nOK: all {len(PACKAGES)} packages declare what they import")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
