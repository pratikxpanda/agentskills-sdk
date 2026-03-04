"""Agent Framework agent with context provider — HTTP provider.

This script demonstrates using :class:`AgentSkillsContextProvider` to
automatically inject skill awareness into an Agent Framework agent,
backed by an HTTP static-file skill provider.

Unlike the manual ``local_tools.py`` approach, the context provider
plugs into the agent lifecycle — no system-prompt assembly required.

Flow:
    1. Create an HTTPStaticFileSkillProvider pointing at a remote host
    2. Register skills in a SkillRegistry
    3. Create an AgentSkillsContextProvider
    4. Pass it as a ``context_providers`` entry when building the agent
    5. Run the agent — skills are injected automatically

Requirements:
    pip install agentskills-http agentskills-agentframework agent-framework --pre
    export AZURE_OPENAI_API_KEY=...
    export AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
    export AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
    export AZURE_OPENAI_API_VERSION=2024-12-01-preview

Usage:
    # Set the base URL to your skill host
    export SKILLS_BASE_URL=https://cdn.example.com/skills
    python examples/agent-framework/http/local_context_provider.py
"""

import asyncio
import os

from agentskills_agentframework import AgentSkillsContextProvider
from agentskills_core import SkillRegistry
from agentskills_http import HTTPStaticFileSkillProvider

# The base URL where skills are hosted. Change this to your own host.
DEFAULT_BASE_URL = "https://cdn.example.com/skills"


async def main() -> None:
    base_url = os.environ.get("SKILLS_BASE_URL", DEFAULT_BASE_URL)

    # ------------------------------------------------------------------
    # 1. Set up the HTTP provider and registry
    # ------------------------------------------------------------------
    async with HTTPStaticFileSkillProvider(base_url) as provider:
        registry = SkillRegistry()
        await registry.register("incident-response", provider)

        print("=== Registered Skills ===")
        for skill in registry.list_skills():
            meta = await skill.get_metadata()
            print(f"  - {meta.get('name', skill.get_id())}: {meta.get('description', '')}")
        print()

        # --------------------------------------------------------------
        # 2. Create the context provider
        # --------------------------------------------------------------
        skills_context_provider = AgentSkillsContextProvider(registry)

        print("=== Skills Context Provider ===")
        print(f"  source_id: {skills_context_provider.source_id}")
        print()

        # --------------------------------------------------------------
        # 3. Initialize Agent Framework agent (requires Azure OpenAI)
        # --------------------------------------------------------------
        try:
            from agent_framework import Agent
            from agent_framework.azure import AzureOpenAIChatClient

            client = AzureOpenAIChatClient(
                deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT"],
                api_version=os.environ["AZURE_OPENAI_API_VERSION"],
            )
        except Exception as e:
            print(f"[SKIP] LLM not available ({e})")
            return

        # No manual system-prompt assembly or tools= list needed!
        # The context provider injects both automatically via before_run().
        agent = Agent(
            client=client,
            name="SREAssistant",
            instructions=(
                "You are an SRE assistant. Use the available skill tools "
                "to look up incident response procedures, severity "
                "definitions, and escalation policies. Always cite which "
                "reference document you used."
            ),
            context_providers=[skills_context_provider],
        )

        # --------------------------------------------------------------
        # 4. Ask a question (streaming)
        # --------------------------------------------------------------
        question = (
            "We have a production outage affecting all users — the "
            "main database is down. What severity is this, what's the "
            "expected response time, and who should I page first?"
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
