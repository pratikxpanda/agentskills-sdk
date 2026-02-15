#!/usr/bin/env python3
"""Development task runner for Pallium.

Usage:
    python scripts/dev.py lint        # Check linting
    python scripts/dev.py format      # Auto-format code
    python scripts/dev.py check       # Lint + type check (no auto-fix)
    python scripts/dev.py test        # Run all tests
    python scripts/dev.py clean       # Remove cache files
    python scripts/dev.py all         # Format + lint + test
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES_DIR = ROOT / "packages"


def _run(cmd: list[str], *, check: bool = True) -> int:
    """Run a command and return its exit code."""
    print(f"\n{'='*60}")
    print(f"  {' '.join(cmd)}")
    print(f"{'='*60}\n")
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result.returncode


# Use sys.executable -m so tools resolve from the active venv.
_PY = sys.executable


def lint() -> None:
    """Run ruff linter (check only, no fixes)."""
    _run([_PY, "-m", "ruff", "check", "packages/", "examples/"])


def lint_fix() -> None:
    """Run ruff linter with auto-fix."""
    _run([_PY, "-m", "ruff", "check", "--fix", "packages/", "examples/"])


def fmt() -> None:
    """Auto-format code with ruff."""
    _run([_PY, "-m", "ruff", "format", "packages/", "examples/"])
    lint_fix()


def fmt_check() -> None:
    """Check formatting without changing files."""
    _run([_PY, "-m", "ruff", "format", "--check", "packages/", "examples/"])


def typecheck() -> None:
    """Run mypy type checking."""
    _run([_PY, "-m", "mypy", "packages/"], check=False)


def check() -> None:
    """Run all checks (format check + lint + type check) without modifying files."""
    fmt_check()
    lint()
    typecheck()


def test() -> None:
    """Run the test suite."""
    _run([_PY, "-m", "pytest", "packages/", "-v"])


def test_cov() -> None:
    """Run tests with coverage report."""
    _run([_PY, "-m", "pytest", "packages/", "-v", "--cov=packages", "--cov-report=term-missing"])


def clean() -> None:
    """Remove all cache and build artifacts."""
    patterns = [
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "*.egg-info",
        "dist",
        "build",
        "htmlcov",
    ]
    removed = 0

    # Skip anything inside the root .venv (the workspace virtualenv)
    root_venv = ROOT / ".venv"

    for pattern in patterns:
        for path in ROOT.rglob(pattern):
            if root_venv in (path, *path.parents):
                continue
            if path.is_dir():
                shutil.rmtree(path)
                print(f"  Removed {path.relative_to(ROOT)}")
                removed += 1
            elif path.is_file():
                path.unlink()
                print(f"  Removed {path.relative_to(ROOT)}")
                removed += 1

    # Also clean .coverage file
    cov_file = ROOT / ".coverage"
    if cov_file.exists():
        cov_file.unlink()
        print("  Removed .coverage")
        removed += 1

    # Clean stray .venv dirs under packages/ (created by poetry build)
    for venv_path in PACKAGES_DIR.rglob(".venv"):
        if venv_path.is_dir():
            shutil.rmtree(venv_path)
            print(f"  Removed {venv_path.relative_to(ROOT)}")
            removed += 1

    if removed == 0:
        print("  Nothing to clean.")
    else:
        print(f"\n  Cleaned {removed} item(s).")


def all_tasks() -> None:
    """Run format + lint + test."""
    fmt()
    lint()
    test()


TASKS = {
    "lint": lint,
    "lint:fix": lint_fix,
    "format": fmt,
    "fmt": fmt,
    "format:check": fmt_check,
    "typecheck": typecheck,
    "check": check,
    "test": test,
    "test:cov": test_cov,
    "clean": clean,
    "all": all_tasks,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        print("Available tasks:")
        for name, fn in TASKS.items():
            print(f"  {name:16s} {fn.__doc__ or ''}")
        sys.exit(0)

    task_name = sys.argv[1]
    task = TASKS.get(task_name)
    if task is None:
        print(f"Unknown task: {task_name}")
        print(f"Available: {', '.join(TASKS.keys())}")
        sys.exit(1)

    task()


if __name__ == "__main__":
    main()
