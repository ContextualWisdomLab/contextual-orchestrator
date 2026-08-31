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


def _wait_for_caplog(caplog, predicate, *, timeout: float = 1.0, interval: float = 0.02) -> None:
    """Poll ``predicate(caplog.text)`` until true or ``timeout`` elapses.

    The per-request INFO summary is logged by a real server thread strictly
    *after* it has already flushed the HTTP response back to the client
    (`server.py`'s ``handle_one_request`` logs in its ``finally`` block,
    which runs after ``super().handle_one_request()`` -- and therefore the
    response write -- completes). A test that asserts on this log line
    immediately after its client call returns has no guarantee the server
    thread has reached that ``finally`` block yet; bounded polling closes
    that race deterministically and quickly in the common case, rather than
    a fixed sleep that is either too short (still flaky) or wastefully long.
    Call this while the relevant ``caplog.at_level(...)`` scope is still
    open, so a late record is not filtered out by the time it arrives.
    """
    import time

    deadline = time.monotonic() + timeout
    while not predicate(caplog.text):
        if time.monotonic() >= deadline:
            return
        time.sleep(interval)


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


def test_session_id_hash_matches_safe_attributes_convention():
    """The shared correlation-hash helper agrees with _safe_attributes' own hashing."""
    assert telemetry_module.session_id_hash() is None
    token = set_session_id("session-safe")
    try:
        assert telemetry_module.session_id_hash() == hashlib.sha256(b"session-safe").hexdigest()
        assert (
            telemetry_module._safe_attributes({})["contextual_orchestrator.session_id_hash"]
            == telemetry_module.session_id_hash()
        )
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


def test_handle_one_request_resets_command_and_path_before_each_call(monkeypatch):
    """Deterministic unit-level counterpart to
    test_keep_alive_close_does_not_log_phantom_request below, which proves
    the same property end to end through a real socket but can occasionally
    flake on unrelated threaded-server teardown timing.

    Simulates stdlib's own `handle_one_request`: the first call "parses" a
    request (setting `command`/`path`, as `parse_request` would), the second
    call reads nothing at all (an empty `raw_requestline` -- a closed
    keep-alive connection) and touches neither attribute, matching real
    stdlib behavior on that path. Without resetting them first, the second
    call would leave the *first* call's `command`/`path` in place, causing
    `_log_request_summary`'s "nothing to report" guard to never fire.
    """
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    call_count = {"n": 0}

    def fake_super_handle_one_request(self):
        call_count["n"] += 1
        if call_count["n"] == 1:
            self.command = "GET"
            self.path = "/healthz"
        # Second call: nothing read, nothing touched (matches stdlib on a
        # closed connection).

    monkeypatch.setattr(BaseHTTPRequestHandler, "handle_one_request", fake_super_handle_one_request)
    try:
        handler.handle_one_request()
        assert handler.command == "GET"
        assert handler.path == "/healthz"

        handler.handle_one_request()
        assert handler.command is None
        assert handler.path is None
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


def test_response_payload_debug_log_reuses_redacted_payload_never_raw_secret(caplog):
    """The DEBUG response summary never carries a secret from an error message.

    Superseded mechanism, same property: this used to prove the secret was
    caught by redact_value and replaced with "[REDACTED]" in an otherwise
    logged error message. It now logs only allowlisted metadata
    (response_metadata_for_log) and never the error message text at all --
    a strictly stronger guarantee, since the secret (and the rest of the
    message) is absent rather than merely masked.
    """
    fake_secret = "sk-FAKEFAKEFAKEFAKEFAKE1234567890"  # noqa: S105 - obviously non-functional fixture
    payload = {
        "choices": [{"message": {"content": "ok"}}],
        "error": {"message": f"upstream rejected request: api_key={fake_secret}"},
    }

    with caplog.at_level("DEBUG", logger="contextual_orchestrator.server"):
        server_module._response_payload(payload, include_trace=True)

    assert "response_summary" in caplog.text
    assert "has_error" in caplog.text
    assert fake_secret not in caplog.text


def test_response_payload_debug_log_redacts_credential_shaped_json_keys(caplog):
    """A secret under a credential-shaped key never reaches the response summary.

    `redact_value`/`redact_text` only pattern-match the literal in-string
    shape `(api[_-]?key|token|secret|password)[:=]<value>` or `bearer
    <value>` -- they never inspect the JSON *key name* a string value is
    nested under. A response payload shaped like `{"private_key": "..."}`,
    `{"key": "..."}`, `{"auth": "..."}`, or `{"credential": "..."}` is now
    caught structurally: the response summary logs only an allowlisted
    metadata shape that never includes these fields at all (see
    `response_metadata_for_log`), with the key-name-based
    `redact_credential_shaped_keys` pass applied on top as a second,
    defense-in-depth layer in case a future allowlist field ever collides
    with a credential-shaped key name.
    """
    fake_private_key = "-----BEGIN PRIVATE KEY-----\nMIIFAKEFAKEFAKE\n-----END PRIVATE KEY-----"
    fake_api_key = "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE12"
    fake_auth = "sk-live-FAKEFAKEFAKEFAKEFAKEFAKEFAKE"
    fake_credential = "ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE"
    payload = {
        "choices": [{"message": {"content": "ok"}}],
        "metadata": {
            "private_key": fake_private_key,
            "key": fake_api_key,
            "auth": fake_auth,
        },
        "credential": fake_credential,
    }

    with caplog.at_level("DEBUG", logger="contextual_orchestrator.server"):
        server_module._response_payload(payload, include_trace=True)

    assert "response_summary" in caplog.text
    assert fake_private_key not in caplog.text
    assert fake_api_key not in caplog.text
    assert fake_auth not in caplog.text
    assert fake_credential not in caplog.text


def test_response_payload_debug_log_never_includes_ordinary_response_content(caplog):
    """CWE-532 (CodeRabbit): the DEBUG summary must never carry response *content*.

    `redact_value`/`redact_credential_shaped_keys` only mask credential-shaped
    content -- ordinary response text (`choices[].message.content`, tool-call
    arguments, an `error.message` that can echo caller-supplied input) is not
    a credential, so it was never masked and reached DEBUG output verbatim.
    That text can carry PII or business-sensitive content that has nothing to
    do with secrets. The summary now logs only an allowlisted metadata shape
    (whether the response is error-shaped, the model name, the choice count,
    and numeric usage counts) and never the payload's actual text.
    """
    sensitive_content = "My SSN is 123-45-6789 and I live at 42 Example Lane."
    sensitive_tool_argument = "wire $50000 to account 000111222 routing 333444555"
    sensitive_error_text = "rejected request containing patient record MRN-778899"
    payload = {
        "id": "chatcmpl-abc123",
        "model": "gpt-test",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": sensitive_content,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "wire_transfer", "arguments": sensitive_tool_argument},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46},
        "error": {"message": sensitive_error_text},
    }

    with caplog.at_level("DEBUG", logger="contextual_orchestrator.server"):
        server_module._response_payload(payload, include_trace=True)

    assert "response_summary" in caplog.text
    assert sensitive_content not in caplog.text
    assert sensitive_tool_argument not in caplog.text
    assert sensitive_error_text not in caplog.text
    # The allowlisted metadata itself is still present.
    assert "gpt-test" in caplog.text
    assert "choice_count" in caplog.text
    assert "46" in caplog.text  # total_tokens, allowlisted numeric usage


def test_response_payload_debug_log_is_silent_without_debug(caplog):
    payload = {"choices": [{"message": {"content": "ok"}}]}

    with caplog.at_level("INFO", logger="contextual_orchestrator.server"):
        server_module._response_payload(payload, include_trace=True)

    assert "response_summary" not in caplog.text


def test_per_request_info_summary_reports_method_path_and_status(caplog):
    """One body-free INFO line per completed request, using method/path/status/latency."""
    import threading
    import time
    import urllib.request

    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with caplog.at_level("INFO", logger="contextual_orchestrator.server"):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
                assert response.status == 200
            _wait_for_caplog(caplog, lambda text: "http_request" in text)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        # ThreadingHTTPServer's per-connection handler threads are daemon
        # threads server_close() does not wait for; a brief settle avoids a
        # straggler's own _log_request_summary call landing inside a *later*
        # test's caplog window instead of being filtered out here at the
        # default WARNING level once this test's own caplog.at_level scope
        # has already exited.
        time.sleep(0.2)

    assert "http_request" in caplog.text
    assert "method=GET" in caplog.text
    assert "path=/healthz" in caplog.text
    assert "status=200" in caplog.text


def test_per_request_info_summary_never_includes_query_string(caplog):
    """The INFO per-request summary logs the bare path only, never a query string.

    A caller could plausibly put a token in a query parameter (a common
    client habit) even though this server's own auth is header-only; the
    summary line's own docstring already claims to be body-free and never
    carry "a query string beyond the raw path", so the raw query string
    (and anything in it) must never reach this log line.
    """
    import threading
    import time
    import urllib.request

    fake_token = "sk-FAKEFAKEFAKEFAKEFAKEQUERYSTRING123"
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with caplog.at_level("INFO", logger="contextual_orchestrator.server"):
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/healthz?api_key={fake_token}", timeout=5
            ) as response:
                assert response.status == 200
            _wait_for_caplog(caplog, lambda text: "http_request" in text)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        time.sleep(0.2)  # see test_per_request_info_summary_reports_method_path_and_status

    assert "http_request" in caplog.text
    assert "path=/healthz" in caplog.text
    assert fake_token not in caplog.text
    assert "?" not in caplog.text


def test_keep_alive_close_does_not_log_phantom_request(caplog):
    """A keep-alive connection closing without a second request logs nothing extra.

    `handle_one_request` never reset `self.command`/`self.path` before each
    call, so when a persistent connection's next read returns nothing (the
    client closed it), those attributes were still whatever the *previous*
    real request left them as. The per-request summary's own "nothing to
    report" guard (`if not method and not path: return`) therefore never
    fired, and the prior request got logged a second time with a statusless
    "phantom" entry.
    """
    import http.client
    import threading
    import time as time_module

    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with caplog.at_level("INFO", logger="contextual_orchestrator.server"):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            assert response.status == 200
            response.read()
            _wait_for_caplog(caplog, lambda text: "http_request" in text)
            connection.close()  # keep-alive connection closed with no second request
            time_module.sleep(0.3)  # let the server's connection thread observe the close
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        time_module.sleep(0.2)  # see test_per_request_info_summary_reports_method_path_and_status

    assert caplog.text.count("http_request") == 1
    assert "path=/healthz" in caplog.text


def test_framework_generated_error_status_is_captured_in_log(caplog):
    """A status the framework sends itself (not via our own writers) is still logged.

    `_last_status` used to be updated only by this module's own
    `_send`/`_send_text`/`_send_bytes`/`_send_sse` writers.
    `BaseHTTPRequestHandler`'s own machinery -- e.g. its built-in 501 for an
    HTTP method with no matching `do_*` handler -- calls `send_response`
    directly and bypasses all of those writers, so the INFO per-request
    summary logged `status=-` even though a real status (501) was already
    sent to the client.
    """
    import http.client
    import threading
    import time

    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with caplog.at_level("INFO", logger="contextual_orchestrator.server"):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("PUT", "/healthz")  # no do_PUT -- stdlib's own 501 path
            response = connection.getresponse()
            assert response.status == 501
            response.read()
            _wait_for_caplog(caplog, lambda text: "http_request" in text)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        time.sleep(0.2)  # see test_per_request_info_summary_reports_method_path_and_status

    assert "http_request" in caplog.text
    assert "status=501" in caplog.text


def test_per_request_info_summary_absent_below_info(caplog):
    import threading
    import time
    import urllib.request

    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with caplog.at_level("WARNING", logger="contextual_orchestrator.server"):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
                assert response.status == 200
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        time.sleep(0.2)  # see test_per_request_info_summary_reports_method_path_and_status

    assert "http_request" not in caplog.text


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


def test_finish_reason_sequence_respects_span_attribute_budget() -> None:
    """One provider response cannot create an unbounded sequence attribute."""
    reasons = [f"reason-{index}" for index in range(256)]
    attributes = telemetry_module._safe_attributes(
        {"gen_ai.response.finish_reasons": reasons}
    )
    assert attributes["gen_ai.response.finish_reasons"] == reasons[:128]


def test_passthrough_response_records_provider_telemetry(monkeypatch) -> None:
    """Feature-rich passthrough responses emit the same evidence as chat."""
    captured: list[dict] = []
    client = ModelClient()
    agent = ModelAgent(
        "worker_agent",
        "gpt-x",
        base_url="https://provider.example/v1",
        credential_key="",
    )

    @contextmanager
    def fake_open(request, destination):  # noqa: ARG001
        yield io.BytesIO(
            json.dumps(
                {
                    "model": "gpt-x-served",
                    "choices": [{"finish_reason": "stop"}],
                    "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(client, "_open_provider", fake_open)
    monkeypatch.setattr(orchestrator_module, "annotate_current_span", captured.append)
    monkeypatch.setattr(orchestrator_module, "record_provider_usage", lambda usage: captured.append(dict(usage)))

    response = client._send_raw(agent, "responses", {"input": "hello"})

    assert response["model"] == "gpt-x-served"
    assert captured[0]["gen_ai.response.model"] == "gpt-x-served"
    assert captured[0]["gen_ai.response.finish_reasons"] == ["stop"]
    assert captured[1] == {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}
