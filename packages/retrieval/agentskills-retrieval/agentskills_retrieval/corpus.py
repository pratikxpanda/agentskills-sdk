"""The searchable text of a skill, and how it is tokenized.

Both selectors rank the same corpus: whatever the catalog would have
shown a model.  Building it here rather than in each selector means a
lexical and an embedding ranking are answering the same question over
the same words, so a difference between them is a difference in method
and not in what they were allowed to read.

``when_not_to_use`` is deliberately kept apart from the rest.  It is
evidence *against* a skill, and folding it into one bag of words would
make a skill match the very query its author wrote it to disclaim.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from hashlib import blake2b
from typing import TYPE_CHECKING, Any

from agentskills_core import SELECTION_FIELDS, get_logger

if TYPE_CHECKING:
    from agentskills_core import Skill, SkillRegistry

_logger = get_logger(__name__)

_WORD = re.compile(r"[a-z0-9]+")

#: Words carried by almost every skill description, so they separate nothing.
#:
#: Deliberately tiny.  A long list is a language model of its own that
#: nobody here is qualified to maintain, and BM25 already discounts a
#: term that appears in most documents.  This exists only to stop very
#: short queries being dominated by their function words.
STOPWORDS = frozenset(
    [
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "how", "in", "into", "is", "it", "of", "on", "or", "that", "the",
        "this", "to", "use", "used", "using", "was", "what", "when",
        "where", "which", "who", "why", "with", "you", "your",
    ]
)  # fmt: skip


def tokenize(text: str) -> list[str]:
    """Split *text* into lowercase alphanumeric terms, minus stopwords.

    No stemming: it would need a dependency, and this package's whole
    claim is that it is useful with none.  The cost is real — "deploys"
    will not match "deploy" — and it is the main thing an embedding
    selector buys back.
    """
    return [word for word in _WORD.findall(text.casefold()) if word not in STOPWORDS]


@dataclass(frozen=True)
class SkillDocument:
    """One skill, as a ranker sees it.

    Attributes:
        skill_id: The registered ID, which is what a selection returns.
        positive_text: Name, description, ``when_to_use`` and tags.
        negative_text: ``when_not_to_use``, scored separately.
        content_hash: Digest of the text above, so an embedding can be
            cached against it and invalidated by nothing else.
    """

    skill_id: str
    positive_text: str
    negative_text: str
    content_hash: str

    @property
    def positive_terms(self) -> list[str]:
        """The tokens a query is matched against."""
        return tokenize(self.positive_text)

    @property
    def negative_terms(self) -> list[str]:
        """The tokens a query is penalised for matching."""
        return tokenize(self.negative_text)


def _strings(value: Any) -> list[str]:
    """Return *value* as a list of non-empty strings, or nothing."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def document_of(skill_id: str, meta: dict[str, Any]) -> SkillDocument:
    """Build the searchable document for one skill's metadata."""
    positive = [
        str(meta.get("name") or skill_id),
        str(meta.get("description") or ""),
        *_strings(meta.get(SELECTION_FIELDS[0])),
    ]
    container = meta.get("metadata")
    if isinstance(container, dict):
        positive += _strings(container.get("tags"))

    negative = _strings(meta.get(SELECTION_FIELDS[1]))

    positive_text = "\n".join(part for part in positive if part)
    negative_text = "\n".join(negative)
    digest = blake2b(f"{positive_text}\x00{negative_text}".encode(), digest_size=16)
    return SkillDocument(
        skill_id=skill_id,
        positive_text=positive_text,
        negative_text=negative_text,
        content_hash=digest.hexdigest(),
    )


async def build_corpus(registry: SkillRegistry, *, concurrency: int = 8) -> list[SkillDocument]:
    """Fetch metadata for every registered skill and index it.

    Args:
        registry: The registry to read.
        concurrency: Ceiling on simultaneous metadata fetches, which
            matters when the provider is network-backed.

    Returns:
        One :class:`SkillDocument` per registered skill, in ID order.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch(skill: Skill) -> SkillDocument:
        async with semaphore:
            return document_of(skill.get_id(), await skill.get_metadata())

    corpus = list(await asyncio.gather(*(fetch(skill) for skill in registry.list_skills())))
    _logger.debug("Indexed %d skills for selection", len(corpus))
    return corpus
