from pathlib import Path

import pytest

from agentskills_adapters import adapt_path
from agentskills_adapters.importers import _ImportedProvider, _slug
from agentskills_core import ResourceNotFoundError


@pytest.mark.asyncio
async def test_imported_provider_rejects_resources():
    provider = _ImportedProvider({"name": "demo"}, "body")

    with pytest.raises(ResourceNotFoundError, match="no scripts"):
        await provider.get_script("demo", "run.sh")
    with pytest.raises(ResourceNotFoundError, match="no assets"):
        await provider.get_asset("demo", "diagram.png")
    with pytest.raises(ResourceNotFoundError, match="no references"):
        await provider.get_reference("demo", "guide.md")


def test_slug_falls_back_for_non_alphanumeric_name():
    assert _slug("!!!") == "imported-skill"


@pytest.mark.asyncio
async def test_source_without_heading_gets_filename_description(tmp_path: Path):
    source = tmp_path / "AGENTS.md"
    source.write_text("Instructions without a heading.", encoding="utf-8")

    imported = adapt_path(source, description="  Explicit description.  ")

    assert (await imported.skill.get_metadata())["description"] == "Explicit description."

    empty = tmp_path / "copilot-instructions.md"
    empty.write_text("Instructions without a heading.", encoding="utf-8")
    imported_empty = adapt_path(empty)
    assert (await imported_empty.skill.get_metadata())["description"] == (
        "Imported instructions from copilot-instructions.md."
    )


def test_frontmatter_must_be_a_mapping(tmp_path: Path):
    source = tmp_path / "AGENTS.md"
    source.write_text("---\n- not a mapping\n---\n\n# Body\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a mapping"):
        adapt_path(source)


def test_directory_without_skill_file_is_rejected(tmp_path: Path):
    source = tmp_path / "claude"
    source.mkdir()

    with pytest.raises(ValueError, match="unsupported adapter source"):
        adapt_path(source)
