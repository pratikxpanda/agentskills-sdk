"""Opt-in, content-free operational events and OpenTelemetry export."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from time import time_ns
from typing import Literal


@dataclass(frozen=True, slots=True)
class DisclosureEvent:
    """A server observation, not evidence of host activation or task success.

    Origin is hashed by ``emit_event`` before reaching observers. Revisions
    describe delivered content. No request IDs, file paths, content, or errors
    are included. Observers are explicitly configured by the application.
    """

    operation: Literal["discovery", "lookup", "fetch", "verification", "refresh", "cache"]
    origin: str
    revision: str | None = None
    status: Literal["ok", "error", "stale"] = "ok"
    byte_count: int = 0
    duration_seconds: float = 0.0
    cache_hit: bool = False


def emit_event(
    observer: Callable[[DisclosureEvent], None] | None,
    operation: Literal["discovery", "lookup", "fetch", "verification", "refresh", "cache"],
    *,
    origin: str,
    revision: str | None = None,
    status: Literal["ok", "error", "stale"] = "ok",
    byte_count: int = 0,
    duration_seconds: float = 0.0,
    cache_hit: bool = False,
) -> None:
    """Emit sanitized metadata without allowing telemetry failures to affect delivery."""
    if observer is None:
        return
    event = DisclosureEvent(
        operation,
        sha256(origin.encode()).hexdigest(),
        revision,
        status,
        byte_count,
        duration_seconds,
        cache_hit,
    )
    try:
        observer(event)
    except Exception:
        return


class OpenTelemetryObserver:
    """Export spans and low-cardinality metrics using application-configured providers.

    Install ``agentskills-core[telemetry]``. This adapter never configures an
    exporter, global SDK provider, endpoint, or credentials. Origins and revisions
    appear on spans only, not on metric labels.
    """

    def __init__(self) -> None:
        from opentelemetry import metrics, trace

        self._tracer = trace.get_tracer("agentskills")
        meter = metrics.get_meter("agentskills")
        self._requests = meter.create_counter("agentskills.operations")
        self._bytes = meter.create_counter("agentskills.bytes", unit="By")
        self._duration = meter.create_histogram("agentskills.duration", unit="s")

    def __call__(self, event: DisclosureEvent) -> None:
        attributes = {
            "operation": event.operation,
            "status": event.status,
            "cache_hit": event.cache_hit,
        }
        self._requests.add(1, attributes)
        self._bytes.add(event.byte_count, attributes)
        self._duration.record(event.duration_seconds, attributes)
        end = time_ns()
        span = self._tracer.start_span(
            "agentskills." + event.operation,
            start_time=end - int(event.duration_seconds * 1_000_000_000),
            attributes={**attributes, "origin": event.origin, "revision": event.revision or ""},
        )
        span.end(end_time=end)
