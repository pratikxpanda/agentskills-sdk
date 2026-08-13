from pathlib import Path

import pytest

from agentskills_adapters import adapt_path, discover_sources, render_skill_md
from agentskills_core import validate_skill


@pytest.mark.asyncio
async def test_agents_file_gets_explicit_description_and_valid_skill(tmp_path: Path):
    source = tmp_path / "AGENTS.md"
    source.write_text(
        "# Repository instructions\n\nUse the project conventions.\n", encoding="utf-8"
    )

    imported = adapt_path(source)

    assert imported.skill.get_id() == "repository-instructions"
    assert (await imported.skill.get_metadata())["description"] == (
        "Imported instructions for Repository instructions."
    )
    assert await validate_skill(imported.skill) == []
    assert "name: repository-instructions" in render_skill_md(imported)


@pytest.mark.asyncio
async def test_cursor_globs_are_preserved_in_metadata(tmp_path: Path):
    source = tmp_path / "deploy.mdc"
    source.write_text(
        "---\ndescription: Deploy services\nglobs: '**/*.yml'\n---\n\n# Deploy\n\nRun deploy.\n",
        encoding="utf-8",
    )

    imported = adapt_path(source)

    metadata = await imported.skill.get_metadata()
    assert metadata["description"] == "Deploy services"
    assert metadata["metadata"] == {"globs": "**/*.yml", "source": "cursor"}
    assert await validate_skill(imported.skill) == []


@pytest.mark.asyncio
async def test_claude_skill_folder_keeps_frontmatter(tmp_path: Path):
    folder = tmp_path / "incident-response"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: incident-response\ndescription: Handle incidents.\n"
        "license: MIT\n---\n\n# Triage\n",
        encoding="utf-8",
    )

    imported = adapt_path(folder)

    assert imported.skill.get_id() == "incident-response"
    assert (await imported.skill.get_metadata())["license"] == "MIT"
    assert await validate_skill(imported.skill) == []


def test_discover_sources_finds_supported_files_without_duplicates(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# Root\n", encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "copilot-instructions.md").write_text("# Copilot\n", encoding="utf-8")
    (tmp_path / ".cursor" / "rules").mkdir(parents=True)
    (tmp_path / ".cursor" / "rules" / "rule.mdc").write_text("# Rule\n", encoding="utf-8")
    (tmp_path / "claude").mkdir()
    (tmp_path / "claude" / "SKILL.md").write_text("# Claude\n", encoding="utf-8")

    assert len(discover_sources(tmp_path)) == 4


def test_unsupported_source_is_explicit(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("notes", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported adapter source"):
        adapt_path(source)
