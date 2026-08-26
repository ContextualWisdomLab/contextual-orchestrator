"""Tests for request session binding and prompt-safe telemetry."""

import hashlib
import io
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import contextual_orchestrator.orchestrator as orchestrator_module
import contextual_orchestrator.server as server_module
import contextual_orchestrator.telemetry as telemetry_module
from contextual_orchestrator.__main__ import _bootstrap_telemetry_config
from contextual_orchestrator.orchestrator import ModelAgent, ModelClient
from contextual_orchestrator.server import build_server
from contextual_orchestrator.telemetry import (
    _otlp_trace_endpoint,
    current_session_id,
    reset_session_id,
    session_id_from_headers,
    session_id_from_metadata,
    session_id_from_request,
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
        session_id_from_headers({"X-LineageWeave-Session-Id": "title-case-session"})
        == "title-case-session"
    )
    assert (
        session_id_from_metadata({"lineageweave_post_session_id": "session-1"})
        == "session-1"
    )
    assert session_id_from_request(
        {"x-lineageweave-session-id": "header-session"},
        {"session_id": "metadata-session"},
    ) == "header-session"
    assert session_id_from_request({}, {"session_id": "metadata-session"}) == "metadata-session"
    assert session_id_from_request({}, None, {"session_id": "later-session"}) == "later-session"
    assert session_id_from_request({}) is None


def test_session_and_attribute_boundaries_reject_unsafe_values():
    """Correlation and span attributes stay bounded, scalar, allowlisted, and prompt-free."""
    assert telemetry_module._config_value(None, "missing", "fallback") == "fallback"
    assert telemetry_module._normalize_session_id(None) is None
    for value in ("", "x" * 129, "line\nbreak"):
        assert telemetry_module._normalize_session_id(value) is None
    assert session_id_from_metadata(None) is None
    assert telemetry_module._safe_attributes({"server.port": object()}) == {}

    token = set_session_id("session-safe")
    try:
        assert telemetry_module._safe_attributes(
            {
                "": "empty-key",
                "nested": {"prompt": "excluded"},
                "prompt": "prompt-secret",
                "response": "response-secret",
                "authorization": "Bearer secret",
                "api_key": "provider-secret",
                "server.address": "x" * 300,
                "server.port": 2,
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "model-x",
                "gen_ai.input.messages": "do not export",
                "long": "x" * 300,
                "enabled": True,
                "attempt": 2,
                "ratio": 0.5,
                "object": object(),
            }
        ) == {
            "server.address": "x" * 256,
            "server.port": 2,
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": "model-x",
            "contextual_orchestrator.session_id_hash": hashlib.sha256(
                b"session-safe"
            ).hexdigest(),
        }
    finally:
        reset_session_id(token)


def test_finish_reason_attribute_accepts_only_bounded_string_arrays():
    """The standard finish-reasons array remains bounded and prompt-safe."""
    assert telemetry_module._safe_attributes(
        {"gen_ai.response.finish_reasons": ["stop", "x" * 300, 2, ""]}
    ) == {"gen_ai.response.finish_reasons": ["stop", "x" * 256]}
    assert telemetry_module._safe_attributes(
        {"gen_ai.response.finish_reasons": {"stop": True}}
    ) == {}


def test_session_binding_is_reset():
    """A request cannot leak its session into a later request context."""
    token = set_session_id("session-2")
    try:
        assert current_session_id() == "session-2"
    finally:
        reset_session_id(token)
    assert current_session_id() is None


def test_local_batch_workers_inherit_session_id(monkeypatch):
    """Concurrent local batch provider spans retain the caller's session."""
    client = ModelClient(local_concurrency=2)
    agent = ModelAgent(
        "local_agent",
        "local-model",
        base_url="local://127.0.0.1:8080/v1",
        local_credential_key="LOCAL_GATEWAY_TOKEN",
    )
    observed: list[str | None] = []

    def fake_chat(_agent, _messages, temperature=None):
        del temperature
        observed.append(current_session_id())
        return "ok"

    monkeypatch.setattr(client, "chat", fake_chat)
    token = set_session_id("post-session")
    try:
        result = client._local_batch_chat(
            agent,
            {"one": [{"role": "user", "content": "1"}], "two": [{"role": "user", "content": "2"}]},
            None,
        )
    finally:
        reset_session_id(token)

    assert set(observed) == {"post-session"}
    assert {key: value["content"] for key, value in result.items()} == {"one": "ok", "two": "ok"}


def test_traced_preserves_provider_error():
    """Tracing records failure but never changes the provider contract."""
    try:
        with traced("contextual_orchestrator.test.failure"):
            raise RuntimeError("provider failure")
    except RuntimeError as exc:
        assert str(exc) == "provider failure"
    else:  # pragma: no cover
        raise AssertionError("traced must preserve operation failures")


def test_traced_preserves_errors_without_optional_status_types(monkeypatch):
    """Tracing remains transparent when optional status helpers are unavailable."""
    monkeypatch.setattr(telemetry_module, "Status", None)
    monkeypatch.setattr(telemetry_module, "StatusCode", None)

    try:
        with traced("contextual_orchestrator.test.optional-status"):
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


def test_configure_telemetry_handles_missing_and_disabled_kv(monkeypatch):
    """Absent configuration is retryable while an explicit disable is final."""
    monkeypatch.setattr(telemetry_module, "_CONFIGURED", False)
    telemetry_module.configure_telemetry(config=None)
    assert telemetry_module._CONFIGURED is False

    disabled = SimpleNamespace(
        get=lambda category, key, default=None: "true" if key == "sdk_disabled" else default
    )
    telemetry_module.configure_telemetry(config=disabled)
    assert telemetry_module._CONFIGURED is True


def test_empty_endpoint_does_not_block_later_collector_configuration(monkeypatch):
    """A partial bootstrap remains retryable until an OTLP endpoint is usable."""
    monkeypatch.setattr(telemetry_module, "_CONFIGURED", False)
    empty = SimpleNamespace(get=lambda category, key, default=None: default)

    telemetry_module.configure_telemetry(config=empty)

    assert telemetry_module._CONFIGURED is False


def test_configure_telemetry_wires_kv_values_to_otlp(monkeypatch):
    """The exporter receives only normalized values read from the injected KV."""
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as exporter_module
    import opentelemetry.sdk.resources as resources_module
    import opentelemetry.sdk.trace as trace_sdk_module
    import opentelemetry.sdk.trace.export as trace_export_module

    exporter = MagicMock()
    processor = MagicMock()
    resource = MagicMock()
    resource.create.return_value = {
        "service.name": "gateway-fallback",
        "service.namespace": "contextualwisdomlab",
    }
    provider_factory = MagicMock()
    fake_trace = MagicMock()
    monkeypatch.setattr(exporter_module, "OTLPSpanExporter", exporter)
    monkeypatch.setattr(resources_module, "Resource", resource)
    monkeypatch.setattr(trace_sdk_module, "TracerProvider", provider_factory)
    monkeypatch.setattr(trace_export_module, "BatchSpanProcessor", processor)
    monkeypatch.setattr(telemetry_module, "trace", fake_trace)
    monkeypatch.setattr(telemetry_module, "_CONFIGURED", False)
    values = {
        "exporter_otlp_endpoint": "http://collector:4318/",
        "service_name": " ",
    }
    config = SimpleNamespace(
        get=lambda category, key, default=None: values.get(key, default)
    )

    telemetry_module.configure_telemetry("gateway-fallback", config=config)
    expected_resource = {
        "service.name": "gateway-fallback",
        "service.namespace": "contextualwisdomlab",
    }
    exporter.assert_called_once_with(endpoint="http://collector:4318/v1/traces")
    resource.create.assert_called_once_with(expected_resource)
    processor.assert_called_once_with(exporter.return_value)
    provider_factory.assert_called_once_with(resource=expected_resource)
    provider_factory.return_value.add_span_processor.assert_called_once_with(
        processor.return_value
    )
    fake_trace.set_tracer_provider.assert_called_once_with(provider_factory.return_value)
    telemetry_module.configure_telemetry(config=config)
    exporter.assert_called_once()


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


def test_handler_replaces_trace_context_on_reauthorization(monkeypatch):
    """A second authorization cannot leave the first trace context attached."""
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    handler.headers = {}
    attached = iter(("first-token", "second-token"))
    detached: list[str] = []
    monkeypatch.setattr(server_module, "attach_trace_context", lambda _headers: next(attached))
    monkeypatch.setattr(server_module, "detach_trace_context", detached.append)
    try:
        handler._bind_trace()
        handler._bind_trace()
        assert detached == ["first-token"]
        assert handler._trace_token == "second-token"
    finally:
        server.server_close()


def test_serve_forwards_telemetry_coordinator(monkeypatch):
    """CLI-provided telemetry configuration reaches the server builder."""
    built = MagicMock()
    build_server = MagicMock(return_value=built)
    monkeypatch.setattr(server_module, "build_server", build_server)
    coordinator = MagicMock()

    server_module.serve(SimpleNamespace(), coordinator=coordinator)

    assert build_server.call_args.kwargs["coordinator"] is coordinator
    built.serve_forever.assert_called_once_with()


def test_http_error_log_excludes_raw_session_id(monkeypatch, caplog):
    """HTTP diagnostics keep request correlation local and omit the raw session value."""
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    handler.path = "/v1/chat/completions"
    monkeypatch.setattr(handler, "_send", lambda *_args, **_kwargs: None)
    token = set_session_id("session-secret")
    try:
        with caplog.at_level("WARNING"):
            handler._send_error(401, "unauthorized", "not authorized")
    finally:
        reset_session_id(token)
        server.server_close()

    assert "request_failed" in caplog.text
    assert "session-secret" not in caplog.text


def test_http_diagnostics_exclude_raw_path_and_swallow_client_disconnect(monkeypatch, caplog):
    """Client cancellation cannot create a second error or leak path identifiers."""
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    handler.path = "/v1/posts/private-record"

    class DisconnectedWriter:
        """Simulate a browser that closes while the response is being written."""

        def write(self, _raw):
            raise BrokenPipeError

        def flush(self):
            raise BrokenPipeError

    handler.wfile = DisconnectedWriter()
    monkeypatch.setattr(handler, "send_response", lambda _status: None)
    monkeypatch.setattr(handler, "send_header", lambda _name, _value: None)
    monkeypatch.setattr(handler, "end_headers", lambda: None)

    with caplog.at_level("DEBUG"):
        handler._send({"detail": "private-record"})
        handler._send_text("private-record", "text/plain")
        handler._send_sse("data: private-record\n\n")
        handler._write_sse("data: private-record\n\n")

    assert "client_disconnected" in caplog.text
    assert "private-record" not in caplog.text
    server.server_close()


def test_provider_calls_use_current_genai_semantic_convention(monkeypatch):
    """Provider spans expose the required, prompt-free GenAI attributes."""
    captured = []

    @contextmanager
    def capture(name, attributes):
        captured.append({"name": name, "attributes": attributes})
        yield None

    client = ModelClient()
    agent = ModelAgent(
        "provider_agent",
        "model-x",
        base_url="https://provider.example/v1",
        credential_key="",
        provider_name="openai",
    )
    monkeypatch.setattr(orchestrator_module, "traced", capture)
    monkeypatch.setattr(client, "_validate_provider", lambda unused_agent: None)
    monkeypatch.setattr(
        client,
        "_send_with_retry",
        lambda unused_agent, unused_payload, unused_destination: "ok",
    )

    assert client.chat(agent, [{"role": "user", "content": "not telemetry"}]) == "ok"
    assert captured == [
        {
            "name": "chat model-x",
            "attributes": {
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": "openai",
                "gen_ai.request.model": "model-x",
                "contextual_orchestrator.agent_id": "provider_agent",
                "server.address": "provider.example",
                "server.port": 443,
            },
        },
    ]


def test_stream_and_passthrough_provider_calls_create_client_spans(monkeypatch):
    """Every non-mock provider transport is represented in the trace."""
    captured: list[tuple[str, str]] = []

    @contextmanager
    def capture(name, attributes):
        captured.append((name, attributes["gen_ai.operation.name"]))
        yield None

    client = ModelClient()
    agent = ModelAgent(
        "provider_agent",
        "model-x",
        base_url="https://provider.example/v1",
        credential_key="",
        provider_name="openai",
    )
    monkeypatch.setattr(orchestrator_module, "traced", capture)
    monkeypatch.setattr(client, "_validate_provider", lambda unused_agent: None)
    monkeypatch.setattr(client, "_stream_send", lambda *_args: iter(("delta",)))
    monkeypatch.setattr(
        client, "_send_raw_with_retry", lambda *_args, **_kwargs: {"ok": True}
    )

    assert list(client.stream_chat(agent, [{"role": "user", "content": "x"}])) == ["delta"]
    assert client.proxy_send(agent, "responses", {"input": "x"}) == {"ok": True}
    assert captured == [
        ("chat model-x", "chat"),
        ("generate_content model-x", "generate_content"),
    ]


def test_traced_starts_safe_client_span_with_error_type_and_no_raw_exception(monkeypatch, caplog):
    """Failures remain classifiable without recording raw exception or session data."""
    tracer = MagicMock()
    span = tracer.start_as_current_span.return_value.__enter__.return_value
    monkeypatch.setattr(telemetry_module.trace, "get_tracer", lambda unused_name: tracer)

    token = set_session_id("session-secret")
    try:
        with traced("chat model-x", {"gen_ai.operation.name": "chat", "prompt": "secret"}):
            error = TimeoutError("provider-response-secret")
            raise error
    except TimeoutError as caught:
        assert caught is error
    finally:
        reset_session_id(token)

    tracer.start_as_current_span.assert_called_once_with(
        "chat model-x",
        kind=telemetry_module.SpanKind.CLIENT,
        attributes={
            "gen_ai.operation.name": "chat",
            "contextual_orchestrator.session_id_hash": hashlib.sha256(
                b"session-secret"
            ).hexdigest(),
        },
        record_exception=False,
        set_status_on_exception=False,
    )
    span.record_exception.assert_not_called()
    # Failures record the CLASSIFIED cause family (network timeout here), not
    # the Python exception class, and never the exception text.
    span.set_attribute.assert_called_once_with("error.type", "provider_connection_error")
    assert "provider-response-secret" not in caplog.text
    assert "session-secret" not in caplog.text


def test_traced_records_upstream_status_for_http_failures(monkeypatch):
    """An upstream HTTP failure exposes its semantic code and original status."""
    import urllib.error

    tracer = MagicMock()
    span = tracer.start_as_current_span.return_value.__enter__.return_value
    monkeypatch.setattr(telemetry_module.trace, "get_tracer", lambda unused_name: tracer)

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        with traced("chat model-x"):
            raise urllib.error.HTTPError(
                "https://p.example", 429, "err", None, io.BytesIO(b"{}")
            )
    assert excinfo.value.code == 429
    span.set_attribute.assert_any_call("error.type", "rate_limit_exceeded")
    span.set_attribute.assert_any_call(
        "contextual_orchestrator.provider_status_code", 429
    )


def test_annotate_and_usage_helpers_filter_to_allowed_genai_attributes():
    """Span annotation keeps approved scalars only; prompts never enter spans."""
    span = MagicMock()
    span.is_recording.return_value = True
    fake_trace = SimpleNamespace(get_current_span=lambda: span)
    original_trace = telemetry_module.trace
    telemetry_module.trace = fake_trace
    try:
        telemetry_module.annotate_current_span(
            {
                "gen_ai.response.model": "gpt-x",
                "gen_ai.usage.input_tokens": 11,
                "gen_ai.usage.output_tokens": 7,
                "gen_ai.usage.total_tokens": 18,
                "prompt": "secret",
                "nested": {"a": 1},
                "bad_ratio": object(),
            }
        )
        telemetry_module.record_provider_usage(
            {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
        )
        telemetry_module.record_provider_usage(None)
    finally:
        telemetry_module.trace = original_trace

    calls = [tuple(call.args) for call in span.set_attribute.call_args_list]
    assert ("gen_ai.response.model", "gpt-x") in calls
    assert ("gen_ai.usage.input_tokens", 11) in calls
    assert ("gen_ai.usage.output_tokens", 7) in calls
    assert ("gen_ai.usage.total_tokens", 18) in calls
    # The second record_provider_usage call re-annotates the OpenAI-keyed counts.
    assert ("gen_ai.usage.input_tokens", 3) in calls
    assert all(key not in {"prompt", "nested"} for key, _value in calls)


def test_record_provider_usage_accepts_responses_style_keys(monkeypatch):
    """``input_tokens``/``output_tokens`` aliases map onto GenAI counts."""
    span = MagicMock()
    span.is_recording.return_value = True
    fake_trace = SimpleNamespace(get_current_span=lambda: span)
    original_trace = telemetry_module.trace
    telemetry_module.trace = fake_trace
    try:
        telemetry_module.record_provider_usage({"input_tokens": 5, "output_tokens": 2})
        # A recording-less span must be a silent no-op.
        empty_span = MagicMock()
        empty_span.is_recording.return_value = False
        telemetry_module.trace = SimpleNamespace(get_current_span=lambda: empty_span)
        telemetry_module.record_provider_usage({"total_tokens": 9})
    finally:
        telemetry_module.trace = original_trace

    calls = [call.args[0] for call in span.set_attribute.call_args_list]
    assert calls == [
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
    ]


def test_record_provider_usage_rejects_negative_counts(monkeypatch):
    """Impossible negative token counts never enter GenAI telemetry."""
    captured: list[dict] = []
    monkeypatch.setattr(telemetry_module, "annotate_current_span", captured.append)
    telemetry_module.record_provider_usage(
        {"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": -3}
    )
    assert captured == [{"gen_ai.usage.output_tokens": 2}]


def test_provider_response_telemetry_records_latency_model_finish_reason(monkeypatch):
    """One completed provider response annotates usage, model, reason, latency."""
    captured: dict[str, list] = {"annotate": [], "usage": []}

    @contextmanager
    def capture(name, attributes):  # noqa: ARG001 - signature parity
        yield None

    class FakeResponse(io.BytesIO):
        pass

    client = ModelClient()
    agent = ModelAgent(
        "worker_agent",
        "gpt-x",
        base_url="https://provider.example/v1",
        credential_key="",
    )

    @contextmanager
    def fake_open(request, destination, timeout=None):  # noqa: ARG001
        yield FakeResponse(
            json.dumps({
                "model": "gpt-x-served",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11},
            }).encode("utf-8")
        )

    monkeypatch.setattr(client, "_validate_provider", lambda unused: None)
    monkeypatch.setattr(client, "_open_provider", fake_open)
    monkeypatch.setattr(orchestrator_module, "traced", capture)
    monkeypatch.setattr(orchestrator_module, "annotate_current_span", lambda a: captured["annotate"].append(a))
    monkeypatch.setattr(orchestrator_module, "record_provider_usage", lambda u: captured["usage"].append(u))

    content = client.chat(agent, [{"role": "user", "content": "hi"}])
    assert content == "ok"
    annotated = captured["annotate"][0]
    assert annotated["gen_ai.response.model"] == "gpt-x-served"
    assert annotated["gen_ai.response.finish_reasons"] == ["stop"]
    assert isinstance(annotated["contextual_orchestrator.latency_ms"], float)
    assert captured["usage"] == [
        {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11}
    ]


def test_provider_response_telemetry_accepts_empty_and_multiple_choices(monkeypatch):
    """Usage-only responses do not crash and all valid finish reasons are recorded."""
    captured: list[dict] = []
    monkeypatch.setattr(orchestrator_module, "annotate_current_span", captured.append)
    monkeypatch.setattr(orchestrator_module, "record_provider_usage", lambda unused: None)

    orchestrator_module._record_provider_response_telemetry({"choices": []}, 0.0)
    orchestrator_module._record_provider_response_telemetry(
        {
            "choices": [
                {"finish_reason": "stop"},
                {"finish_reason": "length"},
                {"finish_reason": None},
                "malformed",
            ]
        },
        0.0,
    )

    assert "gen_ai.response.finish_reasons" not in captured[0]
    assert captured[1]["gen_ai.response.finish_reasons"] == ["stop", "length"]
