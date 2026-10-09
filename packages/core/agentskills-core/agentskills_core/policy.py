"""Content policy applied before publication and after source verification."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from agentskills_core.exceptions import AgentSkillsError
from agentskills_core.snapshots import SkillFile, SkillSnapshot
from agentskills_core.trust import (
    ContentIdentity,
    DetachedSignature,
    TrustPolicy,
    content_revision,
)


class ContentRejectedError(AgentSkillsError):
    """A configured content policy rejected publication."""


@dataclass(frozen=True, slots=True)
class ContentDecision:
    """A hook's replacement bytes, rejection, and deployment-owned annotation codes.

    ``data=None`` preserves bytes. Annotations are not inserted into SKILL.md.
    Hooks are trusted application code. Injection heuristics are advisory only.
    """

    data: bytes | None = None
    reject: bool = False
    annotations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Publication:
    """Delivered bytes and their revision, separate from original publisher evidence."""

    snapshot: SkillSnapshot
    source_identity: ContentIdentity
    revision: str
    annotations: tuple[str, ...] = ()

    @property
    def transformed(self) -> bool:
        """Whether delivered bytes differ from the publisher's verified bytes."""
        return self.revision != self.source_identity.revision


def publish_snapshot(
    snapshot: SkillSnapshot,
    *,
    trust: TrustPolicy,
    proof: DetachedSignature | None = None,
    hooks: Sequence[Callable[[SkillFile], ContentDecision]] = (),
    max_tokens: int | None = None,
    count_tokens: Callable[[str], int] | None = None,
) -> Publication:
    """Verify, apply hooks, bound text tokens, and validate the final file set.

    A token limit requires an explicitly chosen tokenizer, never an implicit
    heuristic. All UTF-8 files count, including frontmatter and nested skills.
    Binary content remains subject to snapshot byte limits. Hook failures abort
    publication. No approval, execution grant, or sandbox is implied.
    """
    if max_tokens is not None and (max_tokens < 0 or count_tokens is None):
        raise ValueError("A nonnegative max_tokens requires an explicit count_tokens function")
    identity = trust.verify(snapshot, proof)
    files: list[SkillFile] = []
    annotations: list[str] = []
    tokens = 0
    for source in snapshot.files:
        file = source
        for hook in hooks:
            decision = hook(file)
            if decision.reject:
                raise ContentRejectedError("Content rejected by publication policy")
            if decision.data is not None:
                if not isinstance(decision.data, bytes):
                    raise ContentRejectedError("Content policy must return bytes")
                file = SkillFile(file.path, decision.data)
            if any(not isinstance(code, str) or len(code) > 128 for code in decision.annotations):
                raise ContentRejectedError("Policy annotations must be bounded string codes")
            annotations.extend(decision.annotations)
        if max_tokens is not None:
            try:
                text = file.data.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None:
                count = count_tokens(text)
                if type(count) is not int or count < 0:
                    raise ContentRejectedError("Tokenizer must return a nonnegative integer")
                tokens += count
                if tokens > max_tokens:
                    raise ContentRejectedError("Content exceeds the configured token limit")
        files.append(file)
    result = SkillSnapshot(snapshot.skill_id, tuple(files))
    return Publication(result, identity, content_revision(result), tuple(annotations))
