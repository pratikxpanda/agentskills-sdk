"""Query-time skill selection for the Agent Skills SDK.

The catalog is injected on every turn, so per-turn prompt cost is
linear in the number of registered skills — and selection accuracy
falls as the candidate list grows, so a large registry is both more
expensive and worse at choosing. This package narrows the catalog to
what the current query is actually about.

Two selectors ship. :class:`LexicalSelector` is BM25 and needs nothing
installed; :class:`EmbeddingSelector` takes any embedder behind a
one-method protocol. Both return scores, and both compose with the
``include=`` filter the registry already has::

    from agentskills_retrieval import LexicalSelector, build_selected_catalog

    selector = LexicalSelector(registry)
    catalog = await build_selected_catalog(registry, selector, "checkout is down")

Nothing here is on by default. A registry that is not asked to select
behaves exactly as it did before this package existed.
"""

from agentskills_retrieval.catalog import build_selected_catalog
from agentskills_retrieval.corpus import (
    STOPWORDS,
    SkillDocument,
    build_corpus,
    document_of,
    tokenize,
)
from agentskills_retrieval.embedding import (
    DEFAULT_MIN_SCORE as DEFAULT_EMBEDDING_MIN_SCORE,
)
from agentskills_retrieval.embedding import (
    Embedder,
    EmbeddingCache,
    EmbeddingSelector,
    InMemoryEmbeddingCache,
    cosine,
    load_embedder,
)
from agentskills_retrieval.lexical import (
    DEFAULT_MIN_SCORE as DEFAULT_LEXICAL_MIN_SCORE,
)
from agentskills_retrieval.lexical import (
    NEGATIVE_WEIGHT,
    LexicalSelector,
)
from agentskills_retrieval.selector import (
    DEFAULT_LIMIT,
    ScoredSkill,
    Selection,
    SkillSelector,
)

__all__ = [
    "DEFAULT_EMBEDDING_MIN_SCORE",
    "DEFAULT_LEXICAL_MIN_SCORE",
    "DEFAULT_LIMIT",
    "NEGATIVE_WEIGHT",
    "STOPWORDS",
    "Embedder",
    "EmbeddingCache",
    "EmbeddingSelector",
    "InMemoryEmbeddingCache",
    "LexicalSelector",
    "ScoredSkill",
    "Selection",
    "SkillDocument",
    "SkillSelector",
    "build_corpus",
    "build_selected_catalog",
    "cosine",
    "document_of",
    "load_embedder",
    "tokenize",
]
