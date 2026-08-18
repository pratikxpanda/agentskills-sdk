"""Embedding-based selection, with no vendor SDK anywhere in the tree.

BM25 cannot match "the site is down" to a skill that says "service
degradation", because they share no word.  Embeddings can, and the
price is a model — so the model stays outside the package, behind a
one-method protocol resolved from a dotted path at run time, exactly
as the eval harness resolves chat models.  Nothing here imports
anything a user did not ask for.

Vectors are cached by content hash, so re-registering an unchanged
skill costs nothing and editing one invalidates only itself.  The cache
is a protocol too: a hosted registry should not re-embed its corpus
every time a process starts.
"""

from __future__ import annotations

import math
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentskills_core import get_logger
from agentskills_retrieval.corpus import SkillDocument, build_corpus
from agentskills_retrieval.selector import DEFAULT_LIMIT, ScoredSkill, Selection

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentskills_core import SkillRegistry

_logger = get_logger(__name__)

#: Cosine similarity below this is treated as no match.
#:
#: Unlike BM25 this floor is meaningful, because cosine is bounded and
#: comparable across corpora.  It is still model-specific — some
#: embedders put unrelated text around 0.7 — so it is a constructor
#: argument and this is only a starting point.
DEFAULT_MIN_SCORE = 0.25


@runtime_checkable
class Embedder(Protocol):
    """The whole contract: a name, and a way to turn text into vectors.

    Implement it over any client::

        class OpenAIEmbedder:
            embedder_id = "text-embedding-3-small"

            async def embed(self, texts):
                reply = await client.embeddings.create(
                    model=self.embedder_id, input=list(texts)
                )
                return [item.embedding for item in reply.data]

    ``embedder_id`` is part of every cache key, because two models'
    vectors are not comparable and a cache that mixes them silently
    returns nonsense.
    """

    embedder_id: str

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text, in the same order."""
        ...


def load_embedder(spec: str) -> Embedder:
    """Resolve ``module:factory`` to an embedder.

    Args:
        spec: A dotted module path, a colon, and the name of a
            zero-argument callable returning an :class:`Embedder`.

    Returns:
        The embedder the factory built.

    Raises:
        ValueError: If the spec is malformed, cannot be imported, or
            does not produce something with ``embedder_id`` and
            ``embed``.
    """
    module_name, _, factory_name = spec.partition(":")
    if not module_name or not factory_name:
        raise ValueError(f"embedder spec must look like 'module:factory', got {spec!r}")

    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"cannot import '{module_name}': {exc}") from exc

    try:
        factory = getattr(module, factory_name)
    except AttributeError as exc:
        raise ValueError(f"'{module_name}' has no attribute '{factory_name}'") from exc

    embedder = factory()
    if not isinstance(embedder, Embedder):
        raise ValueError(
            f"{spec} returned {type(embedder).__name__}, which has no 'embedder_id' and 'embed'."
        )
    return embedder


@runtime_checkable
class EmbeddingCache(Protocol):
    """Somewhere to keep vectors between processes.

    Two methods, both synchronous, because the interesting backends
    (a file, a table, Redis) are all fast enough that making callers
    write an async adapter buys nothing.
    """

    def get(self, key: str) -> list[float] | None:
        """Return the vector stored under *key*, or ``None``."""
        ...

    def set(self, key: str, vector: list[float]) -> None:
        """Store *vector* under *key*."""
        ...


class InMemoryEmbeddingCache:
    """The default cache: a dict that dies with the process."""

    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}

    def get(self, key: str) -> list[float] | None:
        """Return the vector stored under *key*, or ``None``."""
        return self._vectors.get(key)

    def set(self, key: str, vector: list[float]) -> None:
        """Store *vector* under *key*."""
        self._vectors[key] = vector

    def __len__(self) -> int:
        """Number of cached vectors, which is what tests assert on."""
        return len(self._vectors)


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Return the cosine similarity of two vectors, or 0.0 if either is zero."""
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


class EmbeddingSelector:
    """Select skills by cosine similarity between query and skill vectors.

    Args:
        registry: The registry whose skills are ranked.
        embedder: Anything satisfying :class:`Embedder`.  Build one with
            :func:`load_embedder` when the name comes from config.
        cache: Where skill vectors are kept.  Defaults to an in-process
            dict; pass your own to survive a restart.
        min_score: Cosine below this is rejected.  See
            :data:`DEFAULT_MIN_SCORE`.
        negative_weight: How much similarity to ``when_not_to_use``
            subtracts.  Pass ``0.0`` to ignore disclaimers.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        embedder: Embedder,
        *,
        cache: EmbeddingCache | None = None,
        min_score: float = DEFAULT_MIN_SCORE,
        negative_weight: float = 0.5,
    ) -> None:
        self._registry = registry
        self._embedder = embedder
        self._cache: EmbeddingCache = cache if cache is not None else InMemoryEmbeddingCache()
        self._min_score = min_score
        self._negative_weight = negative_weight
        self._corpus: list[SkillDocument] = []
        self._positive: list[list[float]] = []
        self._negative: list[list[float] | None] = []
        self._indexed_ids: tuple[str, ...] = ()

    def _key(self, content_hash: str, field: str) -> str:
        return f"{self._embedder.embedder_id}:{field}:{content_hash}"

    async def _vectors(self, wanted: list[tuple[str, str]]) -> list[list[float]]:
        """Return a vector per ``(cache key, text)``, embedding only misses."""
        cached = [self._cache.get(key) for key, _ in wanted]
        missing = [i for i, vector in enumerate(cached) if vector is None]
        if missing:
            fresh = await self._embedder.embed([wanted[i][1] for i in missing])
            if len(fresh) != len(missing):
                raise ValueError(
                    f"{self._embedder.embedder_id} returned {len(fresh)} vectors "
                    f"for {len(missing)} texts"
                )
            for i, vector in zip(missing, fresh, strict=True):
                self._cache.set(wanted[i][0], vector)
                cached[i] = vector
            _logger.debug(
                "Embedded %d of %d texts; the rest were cached", len(missing), len(wanted)
            )
        return [vector for vector in cached if vector is not None]

    async def index(self) -> None:
        """Embed every registered skill, reusing anything already cached."""
        self._corpus = await build_corpus(self._registry)
        self._positive = await self._vectors(
            [(self._key(doc.content_hash, "pos"), doc.positive_text) for doc in self._corpus]
        )

        negatives = [doc for doc in self._corpus if doc.negative_text]
        vectors = await self._vectors(
            [(self._key(doc.content_hash, "neg"), doc.negative_text) for doc in negatives]
        )
        by_id = dict(zip((doc.skill_id for doc in negatives), vectors, strict=True))
        self._negative = [by_id.get(doc.skill_id) for doc in self._corpus]
        self._indexed_ids = tuple(doc.skill_id for doc in self._corpus)

    async def _ensure_index(self) -> None:
        if self._indexed_ids != tuple(skill.get_id() for skill in self._registry.list_skills()):
            await self.index()

    async def select(self, query: str, *, limit: int = DEFAULT_LIMIT) -> Selection:
        """Return the best *limit* skills for *query*, by cosine similarity."""
        await self._ensure_index()

        [query_vector] = await self._embedder.embed([query])
        scored = []
        for doc, positive, negative in zip(
            self._corpus, self._positive, self._negative, strict=True
        ):
            score = cosine(query_vector, positive)
            if negative is not None:
                score -= self._negative_weight * max(cosine(query_vector, negative), 0.0)
            scored.append(ScoredSkill(doc.skill_id, score))
        scored.sort(key=lambda s: (-s.score, s.skill_id))

        selected = [s for s in scored if s.score > self._min_score][:limit]
        chosen = {s.skill_id for s in selected}
        selection = Selection(
            query=query,
            selected=selected,
            rejected=[s for s in scored if s.skill_id not in chosen],
            considered=len(scored),
        )
        _logger.info("EmbeddingSelector %s", selection.describe())
        return selection
