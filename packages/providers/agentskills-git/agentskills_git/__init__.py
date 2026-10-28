"""Git-backed providers for immutable Agent Skills sources."""

from agentskills_git.provider import GitSkillProvider, GitSkillProviderError

__all__ = ["GitSkillProvider", "GitSkillProviderError"]
