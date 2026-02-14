"""LangChain agent with MCP tools — HTTP provider.

This script demonstrates connecting to an MCP server backed by an HTTP
static-file skill provider from a LangChain agent using
langchain-mcp-adapters.

The client never imports providers or registries — it only talks to the
MCP server over stdio.  The server exposes skill content as MCP tools
and the catalog / usage instructions as MCP resources.

Flow:
    1. Spawn an MCP server subprocess via ``python -m agentskills_mcp_server``
    2. Connect via MultiServerMCPClient
    3. Read MCP resources for the system prompt (catalog + instructions)
    4. Get LangChain tools from the MCP session
    5. Run a LangChain ReAct agent

Requirements:
    pip install agentskills-http agentskills-mcp-server langchain langchain-openai langchain-mcp-adapters
    export AZURE_OPENAI_API_KEY=...
    export AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
    export AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
    export AZURE_OPENAI_API_VERSION=2024-12-01-preview

Usage:
    python examples/langchain/http/mcp_tools.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Path to the skills config file (relative to repo root)
_CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "server-http.json"


async def main() -> None:
    # ------------------------------------------------------------------
    # 1. Connect to MCP server
    # ------------------------------------------------------------------
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        print("[SKIP] langchain-mcp-adapters not installed")
        print("  pip install langchain-mcp-adapters")
        return

    python = sys.executable

    client = MultiServerMCPClient(
        {
            "skills": {
                "command": python,
                "args": ["-m", "agentskills_mcp_server", "--config", str(_CONFIG_FILE)],
                "transport": "stdio",
            }
        }
    )

    # ------------------------------------------------------------------
    # 2. Get LangChain tools
    # ------------------------------------------------------------------
    tools = await client.get_tools()

    print(f"=== MCP Tools ({len(tools)}) ===")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description[:80]}")
    print()

    # ------------------------------------------------------------------
    # 3. Read MCP resources for the system prompt
    # ------------------------------------------------------------------
    async with client.session("skills") as session:
        catalog_result = await session.read_resource("skills://catalog/xml")
        skills_catalog = catalog_result.contents[0].text

        instructions_result = await session.read_resource("skills://tools-usage-instructions")
        tool_usage_instructions = instructions_result.contents[0].text

    print("=== Skills Catalog ===")
    print(skills_catalog)
    print()
    print("=== Tool Usage Instructions ===")
    print(tool_usage_instructions)
    print()

    # ------------------------------------------------------------------
    # 4. Initialize LangChain agent
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

    system_prompt = (
        "You are an SRE assistant. Use the available skill tools "
        "to look up incident response procedures, severity "
        "definitions, and escalation policies. Always cite which "
        "reference document you used.\n\n"
        f"{skills_catalog}\n\n"
        f"{tool_usage_instructions}"
    )

    agent = create_agent(llm, tools, system_prompt=system_prompt)

    # ------------------------------------------------------------------
    # 5. Ask a question
    # ------------------------------------------------------------------
    question = (
        "We have a production outage affecting all users — the "
        "main database is down. What severity is this, what's the "
        "expected response time, and who should I page first?"
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
