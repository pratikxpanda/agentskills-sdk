"""Atomic, audience-scoped publication with opt-in verified stale fallback."""

from __future__ import annotations

import asyncio
import math
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from time import monotonic

from agentskills_core.exceptions import ProviderUnavailableError, SkillUnavailableError
from agentskills_core.policy import Publication
from agentskills_core.snapshots import SkillSnapshot
from agentskills_core.telemetry import DisclosureEvent, emit_event
from agentskills_core.trust import VerificationError


@dataclass(frozen=True, slots=True)
class CatalogGeneration:
    """One all-or-nothing publication for a single authorization audience."""

    publications: tuple[Publication, ...]
    sources: tuple[SkillSnapshot, ...]
    generation: str
    captured_at: float
    stale: bool = False


class SnapshotCatalog:
    """Stage a complete catalog and atomically replace its published generation.

    The loader must make fresh, bounded reads and apply audience authorization.
    Policy is rerun on retained source bytes before stale serving, so revocation
    or changed policy cannot be bypassed by an outage. One instance belongs to
    one audience. Never share it across principals with different access rights.
    The host must still bind approvals to delivered origin and revision.
    """

    def __init__(
        self,
        loader: Callable[[], Awaitable[Sequence[SkillSnapshot]]],
        policy: Callable[[SkillSnapshot], Publication],
        *,
        validate: Callable[[Sequence[Publication]], None] | None = None,
        max_skills: int = 128,
        max_total_bytes: int = 64 * 1024 * 1024,
        max_stale_age: float = 0,
        clock: Callable[[], float] = monotonic,
        observer: Callable[[DisclosureEvent], None] | None = None,
        origin: str = "unconfigured",
    ) -> None:
        if (
            max_skills < 1
            or max_total_bytes < 0
            or not math.isfinite(max_stale_age)
            or max_stale_age < 0
        ):
            raise ValueError("Catalog bounds must be finite and nonnegative, max_skills positive")
        self._loader = loader
        self._policy = policy
        self._validate = validate
        self._max_skills = max_skills
        self._max_total_bytes = max_total_bytes
        self._max_stale_age = max_stale_age
        self._clock = clock
        self._observer = observer
        self._origin = origin
        self._state: CatalogGeneration | None = None
        self._lock = asyncio.Lock()

    @property
    def current(self) -> CatalogGeneration:
        """Return a coherent generation or fail if no eligible catalog is available."""
        state = self._state
        if state is None or (
            state.stale and self._clock() - state.captured_at > self._max_stale_age
        ):
            raise SkillUnavailableError("No ready catalog is available")
        return state

    @property
    def ready(self) -> bool:
        """Report local publication readiness, not transport or authorization health."""
        try:
            _ = self.current
        except SkillUnavailableError:
            return False
        return True

    def _prepare(self, sources: tuple[SkillSnapshot, ...]) -> tuple[Publication, ...]:
        if len(sources) > self._max_skills or len({source.skill_id for source in sources}) != len(
            sources
        ):
            raise ValueError("Catalog has too many skills or duplicate IDs")
        if sum(source.total_bytes for source in sources) > self._max_total_bytes:
            raise ValueError("Source catalog exceeds its byte limit")
        publications = tuple(self._policy(source) for source in sources)
        if any(
            result.snapshot.skill_id != source.skill_id
            for result, source in zip(publications, sources, strict=True)
        ):
            raise ValueError("Policy cannot change a skill identity")
        if sum(result.snapshot.total_bytes for result in publications) > self._max_total_bytes:
            raise ValueError("Published catalog exceeds its byte limit")
        if self._validate is not None:
            self._validate(publications)
        return publications

    async def refresh(self) -> CatalogGeneration:
        """Refresh all content or fail closed, optionally retaining verified outage data.

        Ordinary SkillUnavailableError (including drift) is not an eligible
        outage. No automatic retry loop or background task is created.
        """
        async with self._lock:
            started = self._clock()
            try:
                try:
                    sources = tuple(await self._loader())
                except ProviderUnavailableError:
                    previous = self.current
                    if (
                        self._max_stale_age <= 0
                        or not previous.publications
                        or self._clock() - previous.captured_at > self._max_stale_age
                    ):
                        raise
                    checked = self._prepare(previous.sources)
                    if any(result.source_identity.status != "verified" for result in checked):
                        raise VerificationError(
                            "Stale serving requires verified publishers"
                        ) from None
                    if checked != previous.publications:
                        raise VerificationError(
                            "Policy changed since the last verified capture"
                        ) from None
                    self._state = replace(previous, stale=True)
                else:
                    publications = self._prepare(sources)
                    self._state = CatalogGeneration(
                        publications, sources, secrets.token_urlsafe(18), self._clock()
                    )
            except Exception:
                self._state = None
                emit_event(
                    self._observer,
                    "refresh",
                    origin=self._origin,
                    status="error",
                    duration_seconds=self._clock() - started,
                )
                raise
            state = self.current
            emit_event(
                self._observer,
                "refresh",
                origin=self._origin,
                status="stale" if state.stale else "ok",
                cache_hit=state.stale,
                byte_count=sum(result.snapshot.total_bytes for result in state.publications),
                duration_seconds=self._clock() - started,
            )
            return state
