"""Agent Framework agent with MCP context provider — HTTP provider.

This script demonstrates connecting to an MCP server backed by an HTTP
static-file skill provider using ``AgentSkillsMcpContextProvider`` to
automatically inject skills catalog and usage instructions into each
agent run.

Unlike the manual approach in ``mcp_tools.py`` (which reads MCP
resources directly), this example delegates prompt construction to
:class:`~agentskills_mcp_server.AgentSkillsMcpContextProvider`.  The
context provider reads the catalog and usage-instruction resources from
the MCP session and injects them as session instructions on every
``agent.run()`` call.

Flow:
    1. Spawn an MCP server subprocess via ``python -m agentskills_mcp_server``
    2. Connect via MCPStdioTool (built into Agent Framework)
    3. Create an ``AgentSkillsMcpContextProvider`` from the MCP session
    4. Pass the context provider to the Agent constructor
    5. Run an Agent Framework agent with streaming

Requirements:
    pip install agentskills-http agentskills-mcp-server[agentframework] --pre
    export AZURE_OPENAI_API_KEY=...
    export AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
    export AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
    export AZURE_OPENAI_API_VERSION=2024-12-01-preview

Usage:
    python examples/agent-framework/http/mcp_context_provider.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Path to the skills config file (relative to repo root)
_CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "server-http.json"


async def main() -> None:
    # ------------------------------------------------------------------
    # 1. Connect to MCP server via MCPStdioTool
    # ------------------------------------------------------------------
    try:
        from agent_framework import Agent, MCPStdioTool
        from agent_framework.azure import AzureOpenAIChatClient
    except ImportError:
        print("[SKIP] agent-framework not installed")
        print("  pip install agent-framework --pre")
        return

    try:
        from agentskills_mcp_server import AgentSkillsMcpContextProvider
    except ImportError:
        print("[SKIP] agentskills-mcp-server[agentframework] not installed")
        print("  pip install agentskills-mcp-server[agentframework]")
        return

    python = sys.executable

    mcp_skills = MCPStdioTool(
        name="skills",
        command=python,
        args=["-m", "agentskills_mcp_server", "--config", str(_CONFIG_FILE)],
        description="Agent Skills MCP server (HTTP provider)",
    )

    async with mcp_skills:
        print(f"=== MCP Tools ({len(mcp_skills.functions)}) ===")
        for fn in mcp_skills.functions:
            print(f"  - {fn.name}: {fn.description[:80] if fn.description else ''}")
        print()

        # --------------------------------------------------------------
        # 2. Create context provider from the MCP session
        # --------------------------------------------------------------
        skills_context = AgentSkillsMcpContextProvider(
            session=mcp_skills.session,
        )

        # --------------------------------------------------------------
        # 3. Initialize Agent Framework agent
        # --------------------------------------------------------------
        try:
            client = AzureOpenAIChatClient(
                deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT"],
                api_version=os.environ["AZURE_OPENAI_API_VERSION"],
            )
        except Exception as e:
            print(f"[SKIP] LLM not available ({e})")
            return

        agent = Agent(
            client=client,
            name="SREAssistant",
            instructions=(
                "You are an SRE assistant. Use the available skill "
                "tools to look up incident response procedures, "
                "severity definitions, and escalation policies. "
                "Always cite which reference document you used."
            ),
            tools=mcp_skills,
            context_providers=[skills_context],
        )

        # --------------------------------------------------------------
        # 4. Ask a question (streaming)
        # --------------------------------------------------------------
        question = (
            "We have a production outage affecting all users — the main "
            "database is down. What severity is this, what's the expected "
            "response time, and who should I page first?"
        )

        print("=== Question ===")
        print(question)
        print()

        print("=== Agent Response ===\n")
        pending_calls: dict[str, object] = {}
        last_call_id: str | None = None
        stream = agent.run(question, stream=True)
        async for update in stream:
            for content in update.contents:
                if content.type == "function_call":
                    cid = getattr(content, "call_id", None)
                    if cid:
                        last_call_id = cid
                    else:
                        cid = last_call_id
                    if cid and cid in pending_calls:
                        pending_calls[cid] = pending_calls[cid] + content
                    elif cid:
                        pending_calls[cid] = content
                elif content.type == "function_result":
                    cid = getattr(content, "call_id", None) or ""
                    if cid in pending_calls:
                        pc = pending_calls.pop(cid)
                        print(f"[tool_call] {pc.name}({pc.arguments})")
                    result = content.result
                    if isinstance(result, list):
                        result = "\n".join(getattr(r, "text", str(r)) for r in result)
                    result_str = str(result)
                    preview = result_str[:200]
                    if len(result_str) > 200:
                        preview += "..."
                    print(f"[tool_result] {preview}\n")
                elif content.type == "text":
                    print(content.text, end="", flush=True)
        for pc in pending_calls.values():
            print(f"[tool_call] {pc.name}({pc.arguments})")
        print("\n")


if __name__ == "__main__":
    asyncio.run(main())
