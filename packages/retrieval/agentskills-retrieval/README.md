# agentskills-retrieval

[![PyPI](https://img.shields.io/pypi/v/agentskills-retrieval)](https://pypi.org/project/agentskills-retrieval/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

Query-time skill selection for the [Agent Skills](https://agentskills.io) SDK.

The skills catalog is injected into the system prompt on **every turn**, so its cost is linear in the number of registered skills. Two things get worse as a registry grows, not one: the token bill, and the accuracy of the model's choice. A fifty-skill registry is both more expensive *and* worse at picking the right skill.

`get_skills_catalog()` already accepts `include`, `exclude`, `tags` and `max_chars` — but every one of them requires the caller to know the answer in advance, and `max_chars` drops entries from the end, which is arbitrary with respect to relevance. This package narrows the catalog by *what was asked*.

## Installation

```bash
pip install agentskills-retrieval
```

There are no dependencies beyond `agentskills-core`. The default selector is pure Python.

## Usage

```python
from agentskills_retrieval import LexicalSelector, build_selected_catalog

selector = LexicalSelector(registry)
catalog = await build_selected_catalog(
    registry, selector, "the checkout API is returning 503s"
)
```

Or drive the two halves yourself, which is the whole integration surface:

```python
selection = await selector.select("the checkout API is returning 503s", limit=5)

catalog = await registry.get_skills_catalog(
    include=selection.skill_ids,
    total=selection.considered,
)
```

`include=` is applied **before any metadata is fetched**, so narrowing fifty skills to five also avoids forty-five provider round trips. That matters most for exactly the registries this package exists for.

## Selectors

| Selector | Ranks by | Needs |
| --- | --- | --- |
| `LexicalSelector` | Okapi BM25 over name, description, `when_to_use` and tags | nothing |
| `EmbeddingSelector` | cosine similarity between query and skill vectors | an embedder you supply |

`LexicalSelector` is the default because it works the moment the package is installed. An embedding ranker is better at paraphrase — it can match "the site is down" to a skill that says "service degradation", which BM25 cannot, because they share no word — but it is also an API key, a network hop and a bill. A package whose only ranker needs all three is a package most people never switch on.

### Embedders

No embedding SDK is a dependency of anything here. The contract is one method:

```python
class OpenAIEmbedder:
    embedder_id = "text-embedding-3-small"

    async def embed(self, texts):
        reply = await client.embeddings.create(model=self.embedder_id, input=list(texts))
        return [item.embedding for item in reply.data]
```

```python
from agentskills_retrieval import EmbeddingSelector

selector = EmbeddingSelector(registry, OpenAIEmbedder())
```

`load_embedder("myapp.embedders:build")` resolves the same thing from a dotted path when the name comes from configuration, mirroring how the eval harness resolves chat models.

### Caching

Skill vectors are cached by content hash, so re-registering an unchanged skill is free and editing one invalidates only itself. `embedder_id` is part of every cache key, because two models' vectors are not comparable and a cache that mixes them silently returns nonsense.

The default cache is an in-process dict. Persistence is a two-method protocol — a hosted registry should not re-embed its corpus every time a process starts:

```python
class RedisEmbeddingCache:
    def get(self, key: str) -> list[float] | None: ...
    def set(self, key: str, vector: list[float]) -> None: ...

selector = EmbeddingSelector(registry, embedder, cache=RedisEmbeddingCache())
```

## `when_not_to_use` is a penalty, not a match

Selection metadata is indexed in two halves. `description`, `when_to_use`, the skill name and its tags are evidence *for* a skill. `when_not_to_use` is evidence *against* it, and is scored separately and subtracted.

Folding both into one bag of words would make a skill match the very query its author wrote it to disclaim — "not for local test failures" would make the skill *more* likely to win on a query about a local test failure, because the words line up. The weight is `0.5` rather than `1.0` because a disclaimer is weaker evidence than a description: authors write far fewer of them, and phrase them loosely. Pass `negative_weight=0.0` to ignore them.

## Selection is visible or it is not debuggable

From inside an agent, a skill that was ranked out is indistinguishable from a skill that was never registered. So:

- Every selection is logged at `INFO` on `agentskills.retrieval.*` with the scores that produced it.
- `Selection.rejected` carries what did **not** make the cut, also best-first. "The right skill scored just under the floor" and "the right skill was never registered" are different bugs that look identical without it.
- `build_selected_catalog` passes `total=` so the catalog reports the shortfall itself — `shown`/`total` on the XML root, a closing note in Markdown.

## Floors, and what they can and cannot catch

Returning the five best of fifty irrelevant skills is worse than returning nothing, so both selectors take a `min_score`.

- **Embeddings**: cosine is bounded and comparable across corpora, so the floor is meaningful. The `0.25` default is still model-specific — some embedders put unrelated text around 0.7 — so treat it as a starting point.
- **BM25**: scores are unbounded and corpus-relative, so there is no meaningful absolute floor above zero. The default of `0.0` catches the case that matters — the query shares no term with any skill — but it **cannot** catch a query that matches a common word and is nonetheless irrelevant. That limit is real, and it is why the recall numbers below are measured rather than assumed.

When nothing clears the floor, `build_selected_catalog` returns the **full** catalog. "Selection has no opinion" is not "the agent should have no skills": a wrong prune silently removes a capability, which is a worse failure than a few wasted tokens. The fallback is logged.

## What the query should be

`select()` takes a string and never derives one, because the obvious default is wrong. The last user message alone fails for any conversation where the topic was established several turns ago — "try that again" ranks against nothing. Concatenating the whole history fails the other way, dragging in every topic the conversation has touched. The caller knows its own conversation shape; this package does not, and guessing on its behalf would be a silent accuracy regression rather than an obvious one.

## Measured recall

A ranker shipped without a measurement is a guess with an API. The fixture set in [`tests/conftest.py`](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/retrieval/agentskills-retrieval/tests/conftest.py) pairs realistic queries with the skill that should win, and [`tests/test_recall.py`](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/retrieval/agentskills-retrieval/tests/test_recall.py) asserts a floor that CI enforces, so a change that makes ranking worse fails the build.

`LexicalSelector` over the fixture corpus:

| Metric | Score |
| --- | --- |
| recall@1 | 0.85 |
| recall@3 | 1.00 |

The `EmbeddingSelector` figures are measured against a deterministic hashing embedder, which tests the plumbing rather than any real model's quality; a number from a stub embedder would be a claim about nothing. Run the harness against your own embedder before trusting it in production.

Both numbers are over a small synthetic corpus. They are a regression guard, not a benchmark.

## Not a default

Nothing here is enabled unless you enable it. A registry that is not asked to select behaves exactly as it did before this package existed, byte for byte.

## Security

Selection reads skill metadata only, never bodies or resources. It executes nothing. An embedder you supply is your own code and your own network egress; this package neither imports nor configures one.

## License

MIT
