"""LangChain agent with local tools — filesystem provider.

This script demonstrates using agentskills-langchain to create LangChain
tools directly in-process, backed by a local filesystem skill provider.

Flow:
    1. Create a LocalFileSystemSkillProvider
    2. Register skills in a SkillRegistry
    3. Generate LangChain tools via get_tools()
    4. Build a system prompt with the skill catalog + usage instructions
    5. Run a LangChain ReAct agent

Requirements:
    pip install agentskills-fs agentskills-langchain langchain langchain-openai
    export AZURE_OPENAI_API_KEY=...
    export AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
    export AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
    export AZURE_OPENAI_API_VERSION=2024-12-01-preview

Usage:
    python examples/langchain/fs/local_tools.py
"""

import asyncio
import os
from pathlib import Path

from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_langchain import get_tools, get_tools_usage_instructions


async def main() -> None:
    # ------------------------------------------------------------------
    # 1. Set up the skill provider and registry
    # ------------------------------------------------------------------
    skills_root = Path(__file__).resolve().parent.parent.parent / "skills"
    provider = LocalFileSystemSkillProvider(skills_root)
    registry = SkillRegistry()
    await registry.register("incident-response", provider)

    print("=== Registered Skills ===")
    for skill in registry.list_skills():
        meta = await skill.get_metadata()
        print(f"  - {meta.get('name', skill.get_id())}: {meta.get('description', '')}")
    print()

    # ------------------------------------------------------------------
    # 2. Build tools and system prompt
    # ------------------------------------------------------------------
    tools = get_tools(registry)
    skills_catalog = await registry.get_skills_catalog(format="xml")
    tool_usage_instructions = get_tools_usage_instructions()

    system_prompt = (
        "You are an SRE assistant. Use the available skill tools to look up "
        "incident response procedures, severity definitions, and escalation "
        "policies. Always cite which reference document you used.\n\n"
        f"{skills_catalog}\n\n"
        f"{tool_usage_instructions}"
    )

    print(f"=== Tools ({len(tools)}) ===")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description[:80]}")
    print()

    # ------------------------------------------------------------------
    # 3. Initialize LangChain agent (requires LLM provider)
    # ------------------------------------------------------------------
    try:
        from langchain.agents import create_agent
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        from langchain_openai import AzureChatOpenAI

        llm = AzureChatOpenAI(
            azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            api_version=os.environ["AZURE_OPENAI_API_VERSION"],
            temperature=0,
        )
    except Exception as e:
        print(f"[SKIP] LLM not available ({e})")
        return

    agent = create_agent(llm, tools, system_prompt=system_prompt)

    # ------------------------------------------------------------------
    # 4. Ask a question
    # ------------------------------------------------------------------
    question = (
        "We have a production outage affecting all users — the main database "
        "is down. What severity is this, what's the expected response time, "
        "and who should I page first?"
    )

    print("=== Question ===")
    print(question)
    print()

    print("=== Agent Response ===\n")
    async for chunk in agent.astream(
        {"messages": [HumanMessage(content=question)]},
        stream_mode="updates",
    ):
        for _node, updates in chunk.items():
            for msg in updates.get("messages", []):
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    for tc in msg.tool_calls:
                        print(f"[tool_call] {tc['name']}({tc['args']})")
                elif isinstance(msg, ToolMessage):
                    preview = msg.content[:200]
                    if len(msg.content) > 200:
                        preview += "..."
                    print(f"[tool_result] {msg.name} -> {preview}\n")
                elif isinstance(msg, AIMessage) and msg.content:
                    print(msg.content)
    print()


if __name__ == "__main__":
    asyncio.run(main())
