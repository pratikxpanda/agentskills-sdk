"""Tests for optional user-invoked Skill prompt shortcuts."""

from pathlib import Path

import pytest
from mcp import Client, MCPError

from agentskills_core import Skill
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_mcp_extension import create_mcp_server


def _skill(root: Path, skill_id: str = "alpha") -> tuple[Skill, LocalFileSystemSkillProvider, Path]:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        f"---\nname: {skill_id}\ndescription: A prompt shortcut test.\n---\n\n# First body\n",
        encoding="utf-8",
    )
    provider = LocalFileSystemSkillProvider(root)
    return Skill(skill_id, provider), provider, skill_file


class TestSkillPromptShortcuts:
    async def test_given_prompt_shortcuts_disabled_when_connected_then_no_prompts_are_registered(
        self, tmp_path: Path
    ) -> None:
        skill, _, _ = _skill(tmp_path)
        server = await create_mcp_server([skill], origin="publisher-a")

        async with Client(server) as client:
            assert (await client.list_prompts()).prompts == []

    async def test_given_enabled_shortcut_when_requested_then_returns_current_provenance(
        self, tmp_path: Path
    ) -> None:
        skill, provider, skill_file = _skill(tmp_path)
        server = await create_mcp_server([skill], origin="publisher-a", skill_prompt_shortcuts=True)

        async with Client(server) as client:
            prompts = (await client.list_prompts()).prompts
            assert [prompt.name for prompt in prompts] == ["use-skill"]
            first = await client.get_prompt(
                "use-skill", arguments={"uri": "skill://alpha/SKILL.md"}
            )
            first_text = first.messages[0].content.text
            assert "publisher-a" in first_text
            assert "skill://alpha/SKILL.md" in first_text
            assert "does not grant tool permissions" in first_text
            assert "# First body" in first_text

            skill_file.write_text(
                "---\nname: alpha\ndescription: A prompt shortcut test.\n---\n\n# Updated body\n",
                encoding="utf-8",
            )
            provider.invalidate("alpha")
            await server.refresh()
            second = await client.get_prompt(
                "use-skill", arguments={"uri": "skill://alpha/SKILL.md"}
            )
            second_text = second.messages[0].content.text
            assert "# Updated body" in second_text
            assert "# First body" not in second_text

    async def test_given_unknown_skill_uri_when_prompt_requested_then_rejects_it(
        self, tmp_path: Path
    ) -> None:
        skill, _, _ = _skill(tmp_path)
        server = await create_mcp_server([skill], skill_prompt_shortcuts=True)

        async with Client(server) as client:
            with pytest.raises(MCPError):
                await client.get_prompt("use-skill", arguments={"uri": "skill://missing/SKILL.md"})
