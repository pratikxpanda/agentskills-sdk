"""What a selector is, and what it returns.

A selector answers one question — *given this query, which of these
skills are worth putting in front of the model?* — and it answers it
with scores, not a bare list, because a caller that cannot see why a
skill was dropped cannot debug an agent that failed to use it.

The output composes with the filter the catalog already has::

    selection = await selector.select("the checkout API is down")
    catalog = await registry.get_skills_catalog(
        include=selection.skill_ids,
        total=selection.considered,
    )

``include=`` is applied before any metadata is fetched, so narrowing
fifty skills to five also avoids forty-five provider round trips.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: Skills a selection returns unless the caller asks for more or fewer.
DEFAULT_LIMIT = 5


@dataclass(frozen=True)
class ScoredSkill:
    """One skill and what it scored, in the selector's own units."""

    skill_id: str
    score: float


@dataclass(frozen=True)
class Selection:
    """The outcome of one selection, including what it rejected.

    Attributes:
        query: The text that was ranked against.
        selected: Skills that cleared the floor, best first.
        rejected: Skills that did not, also best first.  Kept because
            "the right skill scored just under the floor" and "the
            right skill was not registered" are different bugs and
            look identical without this.
        considered: How many skills were scored, which is the
            denominator to report in the catalog.
    """

    query: str
    selected: list[ScoredSkill]
    rejected: list[ScoredSkill]
    considered: int

    @property
    def skill_ids(self) -> list[str]:
        """The selected IDs, ready to pass to ``include=``."""
        return [scored.skill_id for scored in self.selected]

    @property
    def is_empty(self) -> bool:
        """Whether nothing cleared the floor."""
        return not self.selected

    def describe(self) -> str:
        """Return a one-line summary with scores, for logs and reports."""
        if self.is_empty:
            best = f", best rejected {self.rejected[0].score:.3f}" if self.rejected else ""
            return f"no skill cleared the floor for {self.query!r} of {self.considered}{best}"
        scores = ", ".join(f"{s.skill_id}={s.score:.3f}" for s in self.selected)
        return f"selected {len(self.selected)} of {self.considered} for {self.query!r}: {scores}"


@runtime_checkable
class SkillSelector(Protocol):
    """Rank registered skills against a query.

    One method, so a caller can supply its own ranker — a hosted
    reranking API, a hand-written routing table — without inheriting
    anything from this package.
    """

    async def select(self, query: str, *, limit: int = DEFAULT_LIMIT) -> Selection:
        """Return the best *limit* skills for *query*, with scores."""
        ...
