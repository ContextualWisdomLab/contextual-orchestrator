"""Tests for request session binding and prompt-safe telemetry."""

from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

from contextual_orchestrator.__main__ import _bootstrap_telemetry_config
from contextual_orchestrator.server import build_server
from contextual_orchestrator.telemetry import (
    _otlp_trace_endpoint,
    current_session_id,
    reset_session_id,
    session_id_from_headers,
    session_id_from_metadata,
    set_session_id,
    traced,
)


def test_session_id_accepts_lineageweave_header_and_metadata():
    """The two compatible transport forms identify the same processing session."""
    assert (
        session_id_from_headers({"x-lineageweave-session-id": "session-1"})
        == "session-1"
    )
    assert (
        session_id_from_metadata({"lineageweave_post_session_id": "session-1"})
        == "session-1"
    )


def test_session_binding_is_reset():
    """A request cannot leak its session into a later request context."""
    token = set_session_id("session-2")
    try:
        assert current_session_id() == "session-2"
    finally:
        reset_session_id(token)
    assert current_session_id() is None


def test_traced_preserves_provider_error():
    """Tracing records failure but never changes the provider contract."""
    try:
        with traced("contextual_orchestrator.test.failure"):
            raise RuntimeError("provider failure")
    except RuntimeError as exc:
        assert str(exc) == "provider failure"
    else:  # pragma: no cover
        raise AssertionError("traced must preserve operation failures")


def test_otlp_base_endpoint_gets_trace_signal_path():
    """Explicit OTLP endpoints use the HTTP traces signal path exactly once."""
    assert _otlp_trace_endpoint("http://collector:4318") == "http://collector:4318/v1/traces"
    assert _otlp_trace_endpoint("http://collector:4318/v1/traces/") == "http://collector:4318/v1/traces"


def test_telemetry_settings_enter_the_process_kv_at_bootstrap(monkeypatch):
    """Runtime telemetry reads a KV populated by the deployment bootstrap."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "gateway-test")
    config = _bootstrap_telemetry_config()
    assert config.get("telemetry", "exporter_otlp_endpoint") == "http://collector:4318"
    assert config.get("telemetry", "service_name") == "gateway-test"


def test_handler_resets_session_after_each_keep_alive_request(monkeypatch):
    """A later request on the same connection cannot inherit the prior session."""
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    monkeypatch.setattr(BaseHTTPRequestHandler, "handle_one_request", lambda self: None)
    try:
        handler._bind_session("first-request")
        assert current_session_id() == "first-request"
        handler.handle_one_request()
        assert current_session_id() is None
    finally:
        server.server_close()
