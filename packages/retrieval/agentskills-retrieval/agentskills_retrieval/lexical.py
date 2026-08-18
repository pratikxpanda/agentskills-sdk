"""BM25 ranking over skill metadata, with no dependencies at all.

This is the default selector, and it is the default because it works
the moment the package is installed.  An embedding selector is better
at paraphrase; it is also an API key, a network hop and a bill, and a
package whose only ranker needs all three is a package most people
never switch on.

Scoring is Okapi BM25 over ``description``, ``when_to_use``, the skill
name and its tags, minus a weighted BM25 over ``when_not_to_use``.  A
skill whose author wrote "not for local test failures" should lose
ground on a query about a local test failure, not gain it for sharing
the vocabulary.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING

from agentskills_core import get_logger
from agentskills_retrieval.corpus import SkillDocument, build_corpus, tokenize
from agentskills_retrieval.selector import DEFAULT_LIMIT, ScoredSkill, Selection

if TYPE_CHECKING:
    from agentskills_core import SkillRegistry

_logger = get_logger(__name__)

#: Term-frequency saturation. The standard value; nothing here justifies tuning it.
K1 = 1.5

#: Length normalisation, also the standard value.
B = 0.75

#: How much a ``when_not_to_use`` match counts against a skill.
#:
#: Below 1.0 on purpose: a disclaimer is weaker evidence than a
#: description, because authors write far fewer of them and phrase them
#: loosely.  At 1.0 a single shared word in a disclaimer could cancel a
#: genuine description match.
NEGATIVE_WEIGHT = 0.5

#: Scores at or below this are treated as no match at all.
#:
#: BM25 is unbounded and corpus-relative, so there is no meaningful
#: absolute floor above zero.  Zero still catches the case that matters
#: — the query shares no term with any skill — but it cannot catch a
#: query that matches a common word and is nonetheless irrelevant.
#: That limit is real and is why recall@k is measured rather than assumed.
DEFAULT_MIN_SCORE = 0.0


class _Bm25Index:
    """A scored field across the corpus."""

    def __init__(self, documents: list[list[str]]) -> None:
        self._lengths = [len(terms) for terms in documents]
        self._avg_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        self._frequencies = [Counter(terms) for terms in documents]

        seen: Counter[str] = Counter()
        for frequency in self._frequencies:
            seen.update(frequency.keys())
        count = len(documents)
        self._idf = {
            # Lucene's variant, which cannot go negative for a term in
            # most documents; the classic form can, and a negative IDF
            # turns a match into a penalty.
            term: math.log(1 + (count - n + 0.5) / (n + 0.5))
            for term, n in seen.items()
        }

    def score(self, index: int, terms: list[str]) -> float:
        """Score document *index* against the query *terms*."""
        if not self._avg_length:
            return 0.0
        frequency = self._frequencies[index]
        length = self._lengths[index]
        total = 0.0
        for term in terms:
            occurrences = frequency.get(term, 0)
            if not occurrences:
                continue
            denominator = occurrences + K1 * (1 - B + B * length / self._avg_length)
            total += self._idf[term] * occurrences * (K1 + 1) / denominator
        return total


class LexicalSelector:
    """Select skills by BM25 over their catalog metadata.

    The corpus is built on first use and reused until the registry's
    set of skill IDs changes, so a long-lived agent pays for indexing
    once.

    Args:
        registry: The registry whose skills are ranked.
        min_score: Scores at or below this are rejected outright.  See
            :data:`DEFAULT_MIN_SCORE` for why the default is zero.
        negative_weight: How much a ``when_not_to_use`` match subtracts.
            Pass ``0.0`` to ignore disclaimers entirely.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        min_score: float = DEFAULT_MIN_SCORE,
        negative_weight: float = NEGATIVE_WEIGHT,
    ) -> None:
        self._registry = registry
        self._min_score = min_score
        self._negative_weight = negative_weight
        self._corpus: list[SkillDocument] = []
        self._positive = _Bm25Index([])
        self._negative = _Bm25Index([])
        self._indexed_ids: tuple[str, ...] = ()

    async def index(self) -> None:
        """Build the BM25 index, discarding any previous one."""
        self._corpus = await build_corpus(self._registry)
        self._positive = _Bm25Index([doc.positive_terms for doc in self._corpus])
        self._negative = _Bm25Index([doc.negative_terms for doc in self._corpus])
        self._indexed_ids = tuple(doc.skill_id for doc in self._corpus)

    async def _ensure_index(self) -> None:
        if self._indexed_ids != tuple(skill.get_id() for skill in self._registry.list_skills()):
            await self.index()

    async def select(self, query: str, *, limit: int = DEFAULT_LIMIT) -> Selection:
        """Return the best *limit* skills for *query*.

        Args:
            query: Free text to rank against.  The caller decides what
                this is; see the README on why the last user message
                alone is a poor default.
            limit: Maximum number of skills to return.

        Returns:
            A :class:`~agentskills_retrieval.Selection`, whose
            ``skill_ids`` feed ``get_skills_catalog(include=...)``.
        """
        await self._ensure_index()

        terms = tokenize(query)
        scored = [
            ScoredSkill(
                doc.skill_id,
                self._positive.score(i, terms)
                - self._negative_weight * self._negative.score(i, terms),
            )
            for i, doc in enumerate(self._corpus)
        ]
        # Ties break by ID so the same registry and query always give
        # the same catalog; a prompt that varies run to run is not one
        # you can debug.
        scored.sort(key=lambda s: (-s.score, s.skill_id))

        selected = [s for s in scored if s.score > self._min_score][:limit]
        chosen = {s.skill_id for s in selected}
        selection = Selection(
            query=query,
            selected=selected,
            rejected=[s for s in scored if s.skill_id not in chosen],
            considered=len(scored),
        )
        _logger.info("LexicalSelector %s", selection.describe())
        return selection
