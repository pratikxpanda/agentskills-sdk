"""The filesystem provider, run against the shared conformance suite.

These tests assert nothing specific to this provider — that is the
point. Anything that fails here is a divergence from the contract every
provider shares, and belongs in ``agentskills-testing`` rather than in
this package's own suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_testing import (
    ASSET_BYTES,
    ASSET_NAME,
    REFERENCE_BYTES,
    REFERENCE_NAME,
    SCRIPT_BYTES,
    SCRIPT_NAME,
    SKILL_ID,
    ContentLimitConformanceSuite,
    ProviderConformanceSuite,
    build_skill,
    render_skill_md,
)


@pytest.fixture
def contract_root(tmp_path: Path) -> Path:
    """A skills directory laid out per the conformance fixture contract."""
    skill_dir = tmp_path / SKILL_ID
    for kind, name, data in (
        ("references", REFERENCE_NAME, REFERENCE_BYTES),
        ("scripts", SCRIPT_NAME, SCRIPT_BYTES),
        ("assets", ASSET_NAME, ASSET_BYTES),
    ):
        (skill_dir / kind).mkdir(parents=True, exist_ok=True)
        (skill_dir / kind / name).write_bytes(data)

    (skill_dir / "SKILL.md").write_text(render_skill_md(build_skill(SKILL_ID)), encoding="utf-8")
    return tmp_path


class TestLocalFileSystemConformance(ProviderConformanceSuite):
    @pytest.fixture
    def provider(self, contract_root: Path) -> LocalFileSystemSkillProvider:
        return LocalFileSystemSkillProvider(contract_root)


class TestLocalFileSystemContentLimits(ContentLimitConformanceSuite):
    @pytest.fixture
    def limited_provider(self, contract_root: Path) -> LocalFileSystemSkillProvider:
        # Smaller than the shortest file in the contract fixture, so every
        # read has to hit the limit.
        return LocalFileSystemSkillProvider(contract_root, max_file_bytes=4)
