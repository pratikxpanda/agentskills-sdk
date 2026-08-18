"""What the context provider remembers between runs of one session.

Agent Framework hands every context provider a ``state`` dict scoped to
that provider and persisted across ``agent.run()`` calls within a
session.  Everything in this module is about using it for two things,
kept separate because they fail differently:

* **Caching** the assembled prompt, which saves provider I/O and is
  safe — the worst case of a stale cache is that it is rebuilt.
* **Recording which skills the agent already loaded**, which changes
  what the next prompt says and therefore has to be right.

State is kept as plain JSON-compatible values.  A host is entitled to
serialise the session, and a ``set`` would not survive the round trip.
"""

from __future__ import annotations

import json
from typing import Any

#: Skills whose **full body** the agent has fetched this session.
LOADED_SKILLS_KEY = "loaded_skills"

#: Where the assembled prompt and the signature it was built from live.
PROMPT_CACHE_KEY = "prompt_cache"

#: Published on ``context.metadata`` so other context providers can see
#: what this one has already put in front of the model.
METADATA_LOADED_SKILLS = "agentskills_loaded_skills"

#: Marks a context this provider has already contributed to, so that a
#: second ``before_run()`` on the same context does not inject twice.
_INJECTED_MARKER = "agentskills_injected"

#: Tool calls that put a skill's whole body in the conversation.
#:
#: Deliberately not ``get_skill_section`` or ``get_skill_outline``: a
#: section is a fragment, and treating a fragment as "loaded" would let
#: the catalog entry be pruned while most of the skill is still unread.
BODY_TOOLS = frozenset({"get_skill_body"})


def loaded_skills(state: dict[str, Any]) -> list[str]:
    """Return the skills whose body has been loaded, in registration-agnostic order."""
    stored = state.get(LOADED_SKILLS_KEY)
    return list(stored) if isinstance(stored, list) else []


def record_loaded(state: dict[str, Any], skill_ids: list[str]) -> list[str]:
    """Add *skill_ids* to the loaded set and return the new set, sorted."""
    merged = sorted({*loaded_skills(state), *skill_ids})
    state[LOADED_SKILLS_KEY] = merged
    return merged


def _skill_id_of(arguments: Any) -> str | None:
    """Pull ``skill_id`` out of a tool call's arguments, whatever shape they arrived in."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (TypeError, ValueError):
            return None
    if isinstance(arguments, dict):
        skill_id = arguments.get("skill_id")
        if isinstance(skill_id, str) and skill_id:
            return skill_id
    return None


def body_loads_in(response: Any) -> list[str]:
    """Return the skill IDs whose body was fetched in *response*.

    Reads function-call content out of the agent's own response rather
    than wrapping the tools, so a caller who built their tools with
    :func:`~agentskills_agentframework.get_tools` and passed them in
    directly is tracked identically to one using the context provider.

    Malformed or unrecognised content is skipped rather than raised on:
    this runs after a successful agent turn, and failing here would
    turn a bookkeeping problem into a failed run.
    """
    found: list[str] = []
    for message in getattr(response, "messages", None) or []:
        for content in getattr(message, "contents", None) or []:
            if getattr(content, "type", None) != "function_call":
                continue
            if getattr(content, "name", None) not in BODY_TOOLS:
                continue
            skill_id = _skill_id_of(getattr(content, "arguments", None))
            if skill_id is not None:
                found.append(skill_id)
    return found


def already_injected(context: Any, source_id: str) -> bool:
    """Return whether this provider has already contributed to *context*."""
    return bool(context.metadata.get(f"{_INJECTED_MARKER}:{source_id}"))


def mark_injected(context: Any, source_id: str) -> None:
    """Record that this provider has contributed to *context*."""
    context.metadata[f"{_INJECTED_MARKER}:{source_id}"] = True


def cached_prompt(state: dict[str, Any], signature: str) -> str | None:
    """Return the cached prompt if it was built from *signature*."""
    cache = state.get(PROMPT_CACHE_KEY)
    if isinstance(cache, dict) and cache.get("signature") == signature:
        prompt = cache.get("prompt")
        return prompt if isinstance(prompt, str) else None
    return None


def store_prompt(state: dict[str, Any], signature: str, prompt: str) -> None:
    """Cache *prompt* against the *signature* it was built from."""
    state[PROMPT_CACHE_KEY] = {"signature": signature, "prompt": prompt}
