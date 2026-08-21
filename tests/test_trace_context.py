"""Tests for prompt-safe inbound W3C trace-context handling."""

import contextual_orchestrator.telemetry as telemetry_module


def test_attach_trace_context_normalizes_headers_and_detaches(monkeypatch):
    """HTTP header casing is normalized and the returned context is releasable."""
    captured = {}
    context = object()
    token = object()

    def fake_extract(carrier):
        captured["carrier"] = carrier
        return context

    def fake_attach(value):
        captured["context"] = value
        return token

    def fake_detach(value):
        captured["token"] = value

    monkeypatch.setattr(telemetry_module, "_otel_extract", fake_extract)
    monkeypatch.setattr(telemetry_module, "_otel_attach", fake_attach)
    monkeypatch.setattr(telemetry_module, "_otel_detach", fake_detach)

    attached = telemetry_module.attach_trace_context({"Traceparent": "00-trace"})
    telemetry_module.detach_trace_context(attached)

    assert captured == {
        "carrier": {"traceparent": "00-trace"},
        "context": context,
        "token": token,
    }


def test_trace_context_is_a_noop_without_the_optional_api(monkeypatch):
    """Missing propagation hooks never change the request contract."""
    monkeypatch.setattr(telemetry_module, "_otel_extract", None)
    monkeypatch.setattr(telemetry_module, "_otel_attach", None)
    monkeypatch.setattr(telemetry_module, "_otel_detach", None)

    assert telemetry_module.attach_trace_context({"traceparent": "ignored"}) is None
    telemetry_module.detach_trace_context(object())
