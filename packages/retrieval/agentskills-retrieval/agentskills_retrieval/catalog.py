"""Turning a selection into a catalog.

The one function here is the whole integration surface: rank, then
hand the winning IDs to the filter ``get_skills_catalog`` already has.
Core learns nothing about ranking; retrieval learns nothing about
rendering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from agentskills_core import get_logger
from agentskills_retrieval.selector import DEFAULT_LIMIT

if TYPE_CHECKING:
    from agentskills_core import SkillRegistry
    from agentskills_retrieval.selector import SkillSelector

_logger = get_logger(__name__)


async def build_selected_catalog(
    registry: SkillRegistry,
    selector: SkillSelector,
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
    format: Literal["xml", "markdown"] = "xml",
    **catalog_kwargs: Any,
) -> str:
    """Rank the registry against *query* and build a catalog of the winners.

    The result reports its own narrowing — ``shown``/``total`` on the
    XML root, a closing note in Markdown — because from inside an agent
    a skill that was ranked out is indistinguishable from one that was
    never registered, and that is a miserable thing to debug.

    When nothing clears the selector's floor the **full** catalog is
    returned. "Selection has no opinion" is not "the agent should have
    no skills": a wrong prune silently removes a capability, which is a
    worse failure than a few wasted tokens. The fallback is logged.

    Args:
        registry: The registry to build from.
        selector: Any :class:`~agentskills_retrieval.SkillSelector`.
        query: Text to rank against.
        limit: Maximum number of skills to advertise.
        format: ``"xml"`` or ``"markdown"``, as for
            :meth:`~agentskills_core.SkillRegistry.get_skills_catalog`.
        **catalog_kwargs: Passed straight through to
            :meth:`~agentskills_core.SkillRegistry.get_skills_catalog`.
            ``include`` and ``total`` are supplied by this function.

    Returns:
        A catalog string ready for a system prompt.
    """
    selection = await selector.select(query, limit=limit)
    if selection.is_empty:
        _logger.info(
            "Selection matched nothing for %r; falling back to the full catalog of %d skills",
            query,
            selection.considered,
        )
        return await registry.get_skills_catalog(format=format, **catalog_kwargs)

    return await registry.get_skills_catalog(
        format=format,
        include=selection.skill_ids,
        total=selection.considered,
        **catalog_kwargs,
    )
