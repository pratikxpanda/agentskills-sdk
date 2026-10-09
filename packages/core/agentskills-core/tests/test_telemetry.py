"""Disclosure telemetry excludes content and does not change delivery outcomes."""

from types import SimpleNamespace

from agentskills_core.telemetry import OpenTelemetryObserver, emit_event


def test_given_observer_failure_when_emitting_then_delivery_is_unaffected():
    def broken(event):
        raise RuntimeError("secret")

    emit_event(broken, "fetch", origin="secret", revision="sha256:abc")


def test_given_otel_observer_when_emitting_then_metrics_remain_low_cardinality(monkeypatch):
    from opentelemetry import metrics, trace

    records = []
    spans = []
    instrument = SimpleNamespace(
        add=lambda value, attrs: records.append((value, attrs)),
        record=lambda value, attrs: records.append((value, attrs)),
    )
    meter = SimpleNamespace(
        create_counter=lambda *args, **kwargs: instrument,
        create_histogram=lambda *args, **kwargs: instrument,
    )

    def start_span(name, **kwargs):
        spans.append((name, kwargs))
        return SimpleNamespace(end=lambda **kwargs: None)

    monkeypatch.setattr(metrics, "get_meter", lambda name: meter)
    monkeypatch.setattr(trace, "get_tracer", lambda name: SimpleNamespace(start_span=start_span))

    emit_event(
        OpenTelemetryObserver(),
        "fetch",
        origin="https://secret.example/?sig=secret",
        revision="sha256:abc",
        byte_count=123,
        duration_seconds=0.5,
        cache_hit=True,
    )

    assert [record[0] for record in records] == [1, 123, 0.5]
    assert all(set(record[1]) == {"operation", "status", "cache_hit"} for record in records)
    assert "secret" not in repr(spans)
    assert spans[0][1]["attributes"]["revision"] == "sha256:abc"
