"""Shared fixtures: skills on disk, written as text so tests can break them."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

VALID = """---
name: {name}
description: A skill for testing.
version: 1.0.0
---

# Test

Body text.
"""


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    """An empty directory to write skill folders into."""
    root = tmp_path / "skills"
    root.mkdir()
    return root


@pytest.fixture
def write_skill(skills_root: Path) -> Callable[..., Path]:
    """Write a skill folder, defaulting to a valid ``SKILL.md``."""

    def _write(name: str, text: str | None = None) -> Path:
        path = skills_root / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text(text if text is not None else VALID.format(name=name))
        return path

    return _write


@pytest.fixture
def write_eval(skills_root: Path) -> Callable[..., Path]:
    """Write an eval file into a skill folder."""

    def _write(skill: str, text: str, name: str = "cases.yaml") -> Path:
        evals = skills_root / skill / "evals"
        evals.mkdir(parents=True, exist_ok=True)
        path = evals / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write
