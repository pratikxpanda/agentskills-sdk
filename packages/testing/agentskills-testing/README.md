# agentskills-testing

Conformance suite and test doubles for [Agent Skills](https://agentskills.io) providers.

`SkillProvider` is an abstract base class, which enforces that five methods exist
and nothing whatsoever about what they do. The requirements that actually matter
are the ones an ABC cannot express: that an unknown skill ID raises
`SkillNotFoundError` rather than returning `{}`, that `../../etc/passwd` is
refused rather than resolved, and that a provider advertising resource listing
can actually list. This package turns those into tests you inherit.

```bash
pip install agentskills-testing
```

## Conformance suite

Subclass `ProviderConformanceSuite`, supply a `provider` fixture, and pytest
collects the entire provider contract against your implementation:

```python
import pytest

from agentskills_testing import ProviderConformanceSuite

from my_package import MyProvider


class TestMyProvider(ProviderConformanceSuite):
    @pytest.fixture
    def provider(self):
        return MyProvider(...)
```

### Fixture contract

The `provider` fixture must expose exactly one skill:

| | |
| --- | --- |
| id | `conformance-skill` |
| metadata | `name == "conformance-skill"`, plus a non-empty `description` |
| body | non-empty markdown |
| `references/` | `notes.md` containing `b"# Notes\n\nA reference document.\n"` |
| `scripts/` | `run.sh` containing `b"#!/bin/sh\necho conformance\n"` |
| `assets/` | `diagram.svg` containing `b"<svg></svg>\n"` |

It must not define a skill called `no-such-skill-anywhere`, or any resource
called `no-such-resource.txt`.

Every name and byte string above is exported as a constant (`SKILL_ID`,
`REFERENCE_NAME`, `REFERENCE_BYTES`, and so on), so a fixture can be built from
them rather than from copied literals. `CONTRACT` holds the same description as
a string, and is what the default fixture prints when you forget to override it.

### What it checks

- Metadata carries `name` and a non-empty `description`, and does **not** carry
  the body — a metadata call that includes the body has already spent the tokens
  progressive disclosure exists to save.
- Metadata is not shared mutable state: one caller mutating the returned dict
  must not affect the next.
- Repeated reads agree. A provider that streams without buffering passes the
  first read and returns empty on the second; caching bugs look the same.
- Each resource getter returns exact `bytes`, not `str`. A resource may be a
  PNG, and decoding on the way out makes that unreachable.
- Unknown skills raise `SkillNotFoundError`; unknown resources raise
  `ResourceNotFoundError`.
- `list_resources()` agrees with `supports_resource_listing`. Callers branch on
  that flag, so a provider whose flag and behaviour disagree breaks them
  whichever way it lies.
- `discover()` agrees with `supports_discovery`, and everything it reports can
  actually be read. `register_all()` validates the whole list, so one phantom ID
  fails the entire registration.
- **Traversal identifiers are refused** — parent traversal, absolute paths,
  Windows separators, percent-encoded traversal, and embedded NUL bytes, as both
  skill IDs and resource names. These are not opt-out.
- Concurrent reads through a single instance return consistent content, which
  catches per-call state stored on `self`.

### Size limits

`ContentLimitConformanceSuite` is separate and opt-in. A size limit is not part
of the universal contract — an in-memory provider has no external source to
bound, and demanding one would assert a filesystem's constraints against a dict.
It **is** required of any provider that reads bytes it did not author: from
disk, from a network, from anywhere a caller can grow without asking.

```python
from agentskills_testing import ContentLimitConformanceSuite


class TestMyProviderLimits(ContentLimitConformanceSuite):
    @pytest.fixture
    def limited_provider(self):
        return MyProvider(..., max_bytes=8)
```

The fixture holds the same skill, with a limit small enough that the skill
exceeds it.

## Test doubles

`InMemorySkillProvider` is a real, spec-compliant provider backed by a dict — it
passes the conformance suite above. Prefer it to an `AsyncMock`: a mock agrees
with whatever the test asserts, including the assertions that are wrong.

```python
from agentskills_core import SkillRegistry
from agentskills_testing import InMemorySkillProvider, build_skill

provider = InMemorySkillProvider(
    {
        "incident-response": build_skill(
            "incident-response",
            description="Diagnose and mitigate a production incident.",
            body="# Incident Response\n\nPage the on-call engineer.\n",
            references={"severity-levels.md": b"SEV1 is customer-visible.\n"},
        )
    }
)

registry = SkillRegistry()
await registry.register_all(provider)
```

A string value is taken as the body, for the common case where the content does
not matter:

```python
provider = InMemorySkillProvider({"a": "body of a", "b": "body of b"})
provider.add("c")  # a default skill named "c"
```

`build_skill()` produces frontmatter that passes `validate_skill()`, so a test
that does not care about metadata does not have to invent any.
`render_skill_md(skill)` renders one back to `SKILL.md` text, which is how you
populate a temporary directory for the filesystem provider.

To emulate a backend that cannot enumerate — a static HTTP host without a
manifest, for instance — pass `supports_resource_listing=False`, or
`supports_discovery=False`, or both.

## Fixtures

Installing the package registers a pytest plugin, so these are available with no
import and no `conftest.py` entry:

| Fixture | What you get |
| --- | --- |
| `sample_skill` | An `InMemorySkill` with one reference, one script, and one asset |
| `skill_provider` | An `InMemorySkillProvider` serving `sample_skill` |
| `skill_registry` | A `SkillRegistry` with that skill already registered |

```python
async def test_my_agent(skill_registry):
    catalog = await skill_registry.get_skills_catalog()
    assert "incident-response" in catalog
```

## License

MIT — see [LICENSE](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE).

Part of the [Agent Skills SDK](https://github.com/pratikxpanda/agentskills-sdk).
