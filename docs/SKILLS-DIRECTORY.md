# Agent Skills Directory

A curated directory of [Agent Skills](https://agentskills.io) repositories, awesome lists, and community resources. Use these as inspiration, reference implementations, or load them into your own agents using the [HTTP provider](../packages/providers/agentskills-http/README.md).

---

## Official Skills Repositories

| Repository | Description |
| --- | --- |
| [anthropics/skills](https://github.com/anthropics/skills) | Anthropic's official skill examples: documents, creative, development tools, and more |
| [microsoft/skills](https://github.com/microsoft/skills) | Skills, MCP servers, and custom agents for Azure SDK and Microsoft AI Foundry development |
| [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | Vercel's official collection of agent skills for React, web design, and deployment |
| [trailofbits/skills](https://github.com/trailofbits/skills) | Trail of Bits skills for security research, vulnerability detection, and audit workflows |
| [agentskills/agentskills](https://github.com/agentskills/agentskills) | Agent Skills specification and documentation |

---

## Community Skills

Top community repositories sorted by [GitHub stars](https://github.com/search?q=awesome+agent+skills&type=repositories&s=stars&o=desc).

| Repository | Description |
| --- | --- |
| [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) | 874+ SaaS app automation skills via Composio toolkits, plus curated community skills across document processing, development, data analysis, business, creative, and productivity categories |
| [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | Skills, hooks, slash-commands, agent orchestrators, and plugins for Claude Code |
| [sickn33/antigravity-awesome-skills](https://github.com/sickn33/antigravity-awesome-skills) | 800+ agentic skills for Claude Code, Antigravity, and Cursor |
| [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) | 300+ agent skills from official dev teams and the community, compatible with Codex, Antigravity, Gemini CLI, Cursor, and more |
| [heilcheng/awesome-agent-skills](https://github.com/heilcheng/awesome-agent-skills) | Skills, tools, tutorials, and capabilities for AI coding agents (Claude, Codex, Copilot, VS Code) |
| [libukai/awesome-agent-skills](https://github.com/libukai/awesome-agent-skills) | Agent Skills guide with quick start, recommended skills, latest news, and practical examples |
| [Prat011/awesome-llm-skills](https://github.com/Prat011/awesome-llm-skills) | LLM and AI Agent Skills, resources, and tools for Claude Code, Codex, Gemini CLI, and more |
| [SamurAIGPT/awesome-openclaw](https://github.com/SamurAIGPT/awesome-openclaw) | Resources, tools, skills, tutorials, and articles for the OpenClaw AI agent |
| [rohitg00/awesome-claude-code-toolkit](https://github.com/rohitg00/awesome-claude-code-toolkit) | Agents, curated skills, commands, plugins, and hooks for Claude Code |
| [Code-and-Sorts/awesome-copilot-agents](https://github.com/Code-and-Sorts/awesome-copilot-agents) | Curated list of instructions, prompts, skills, and agent markdown files for GitHub Copilot |

---

## Using Skills with This SDK

Any skill hosted on a web server can be loaded using the [HTTP provider](../packages/providers/agentskills-http/README.md):

```python
from agentskills_core import SkillRegistry
from agentskills_http import HTTPStaticFileSkillProvider

provider = HTTPStaticFileSkillProvider("https://example.com/skills")
registry = SkillRegistry()
await registry.register("my-skill", provider)
```

For skills stored locally, use the [filesystem provider](../packages/providers/agentskills-fs/README.md):

```python
from pathlib import Path
from agentskills_fs import LocalFileSystemSkillProvider

provider = LocalFileSystemSkillProvider(Path("path/to/skills"))
```

---

## Contributing

Know of a skill repository or resource that should be listed here? Open an issue or submit a PR to add it.
