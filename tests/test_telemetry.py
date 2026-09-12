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


def _start_test_server(server):
    """Join test-owned request handlers before capture teardown."""
    import threading

    server.daemon_threads = False
    serving_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serving_thread.start()
    return serving_thread


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
    assert telemetry_module._safe_attributes({"server.address": "10.0.0.9"}) == {}
    assert telemetry_module._safe_attributes({"server.address": "fd00::9"}) == {}

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
    captured_send = MagicMock()
    monkeypatch.setattr(handler, "_send", captured_send)
    token = set_session_id("session-secret")
    try:
        with caplog.at_level("WARNING"):
            handler._send_error(
                401, "unauthorized", "not authorized",
                {"request_id": "untrusted\nlog-injection", "reason": "private-detail"},
            )
    finally:
        reset_session_id(token)
        server.server_close()

    assert "request_failed" in caplog.text
    response_payload = captured_send.call_args.args[0]
    response_request_id = response_payload["error"]["detail"]["request_id"]
    warning_messages = [
        record.getMessage() for record in caplog.records
        if record.name == "contextual_orchestrator.server"
        and record.getMessage().startswith("request_failed ")
    ]
    assert warning_messages == [
        f"request_failed status=401 code=unauthorized request_id={response_request_id}"
    ]
    assert response_request_id != "untrusted\nlog-injection"
    assert len(response_request_id) == 32
    assert all(character in "0123456789abcdef" for character in response_request_id)
    assert response_payload["error"]["detail"]["reason"] == "private-detail"
    assert "untrusted" not in caplog.text
    assert "private-detail" not in caplog.text
    assert "session-secret" not in caplog.text


def test_http_error_ids_correlate_over_real_connections(caplog):
    """Separate HTTP errors carry distinct IDs matching their server warnings."""
    import http.client
    import threading

    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    server_thread = _start_test_server(server)
    request_ids = []
    with caplog.at_level("WARNING", logger="contextual_orchestrator.server"):
        try:
            for _request_index in range(2):
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                try:
                    connection.request("GET", "/v1/models")
                    with connection.getresponse() as response:
                        assert response.status == 401
                        payload = json.loads(response.read())
                        request_id = payload["error"]["detail"]["request_id"]
                        request_ids.append(request_id)
                        expected_message = (
                            f"request_failed status=401 code={payload['error']['code']} "
                            f"request_id={request_id}"
                        )
                        assert expected_message in [record.getMessage() for record in caplog.records]
                finally:
                    connection.close()
        finally:
            server.shutdown()
            server_thread.join(timeout=5)
            server.server_close()
    assert len(set(request_ids)) == 2


def test_provider_diagnostic_events_preserve_request_identity(caplog):
    """Every retry outcome keeps trusted identity before untrusted error text."""
    agent = ModelAgent("diagnostic_agent", "mock-model")
    failure = RuntimeError("controlled error")
    with caplog.at_level("DEBUG"), telemetry_module.request_identity() as request_id:
        orchestrator_module._log_provider_attempt(agent, 0, 1)
        orchestrator_module._log_provider_attempt_failed(agent, 0, failure, False)
        orchestrator_module._log_provider_backoff(agent, 0, 0.0)
        orchestrator_module._log_provider_exhausted(agent, 2, failure)
        orchestrator_module._log_provider_no_retry_budget(agent, 1, failure, transient=False)
        orchestrator_module._log_provider_one_shot_call_failed(agent, 1, failure, transient=False)
        orchestrator_module._log_provider_rejected_permanent(agent, 1, failure)
    messages = [row.getMessage() for row in caplog.records if row.name == orchestrator_module.__name__]
    assert len(messages) == 7
    assert all(f"request_id={request_id}" in message for message in messages)
    assert f"request_id={request_id} error_message=" in messages[1]


def test_request_identity_restores_context_across_threads_and_failure():
    """Copied work inherits identity; reused workers and failed scopes do not leak it."""
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context

    assert telemetry_module.current_request_id() is None
    with ThreadPoolExecutor(max_workers=1) as executor:
        with telemetry_module.request_identity() as outer_id:
            assert executor.submit(copy_context().run, telemetry_module.current_request_id).result() == outer_id
            assert executor.submit(telemetry_module.current_request_id).result() is None
            with pytest.raises(RuntimeError):
                with telemetry_module.request_identity() as inner_id:
                    assert inner_id != outer_id
                    raise RuntimeError("controlled failure")
            assert telemetry_module.current_request_id() == outer_id
        assert telemetry_module.current_request_id() is None
        assert executor.submit(telemetry_module.current_request_id).result() is None


def test_provider_attempts_share_http_error_identity(monkeypatch, caplog):
    """Same-session HTTP requests need distinct identities before provider failure."""
    import http.client
    import threading
    from contextual_orchestrator import TaskOrchestrator
    from contextual_orchestrator.server import SecurityConfig

    model_agent = ModelAgent("correlation_agent", "mock-model")
    model_client = ModelClient(max_retries=0)
    router = TaskOrchestrator([model_agent], client=model_client)

    def reject_send(*args, **kwargs):
        raise RuntimeError("controlled provider failure")

    def fail_completion(*args, **kwargs):
        return model_client._send_with_retry(model_agent, {})

    monkeypatch.setattr(model_client, "_send", reject_send)
    monkeypatch.setattr(router, "complete", fail_completion)
    server = build_server(router, port=0, security=SecurityConfig(auth_token="test-correlation-token"))
    server_thread = _start_test_server(server)
    connection = http.client.HTTPConnection(*server.server_address, timeout=5)
    request_ids = []
    first_socket = None
    with caplog.at_level("DEBUG"):
        try:
            for request_index in range(2):
                first_record = len(caplog.records)
                connection.request("POST", "/v1/chat/completions", json.dumps({
                    "model": "mock-model", "messages": [{"role": "user", "content": "unit request"}],
                }), {
                    "Content-Type": "application/json", "Authorization": "Bearer test-correlation-token",
                    "X-LineageWeave-Session-Id": "shared-private-session",
                })
                if first_socket is None:
                    first_socket = connection.sock
                    assert first_socket is not None
                else:
                    assert connection.sock is first_socket
                with connection.getresponse() as response:
                    assert response.status >= 400
                    assert not response.will_close
                    response_body = json.loads(response.read())
                    request_id = response_body["error"]["detail"]["request_id"]
                    request_ids.append(request_id)
                    attempt_logs = [record.getMessage() for record in caplog.records[first_record:]
                                    if record.getMessage().startswith(("provider_attempt ", "provider_attempt_failed "))]
                    assert len(attempt_logs) == 2, (request_index, attempt_logs)
                    assert all(f"request_id={request_id}" in message for message in attempt_logs)
            assert len(set(request_ids)) == 2
            assert "shared-private-session" not in "\n".join(attempt_logs)
        finally:
            connection.close()
            server.shutdown()
            server_thread.join(timeout=5)
            server.server_close()
            router.close()


def test_concurrent_http_provider_identity_isolation(monkeypatch, caplog):
    """Overlapping same-session requests keep their own provider/error identities."""
    import http.client
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from contextual_orchestrator import TaskOrchestrator
    from contextual_orchestrator.server import SecurityConfig

    rendezvous = threading.Barrier(2, timeout=10)
    overlapping_threads = set()
    overlap_lock = threading.Lock()
    model_agent = ModelAgent("parallel_agent", "mock-model")
    model_client = ModelClient(max_retries=0)
    router = TaskOrchestrator([model_agent], client=model_client)

    def reject_send(*args, **kwargs):
        rendezvous.wait()
        with overlap_lock:
            overlapping_threads.add(threading.get_ident())
        raise RuntimeError("controlled overlapping failure")

    def fail_completion(*args, **kwargs):
        return model_client._send_with_retry(model_agent, {})

    monkeypatch.setattr(model_client, "_send", reject_send)
    monkeypatch.setattr(router, "complete", fail_completion)
    server = build_server(router, port=0, security=SecurityConfig(auth_token="parallel-test-token"))
    server_thread = _start_test_server(server)

    def send_request():
        connection = http.client.HTTPConnection(*server.server_address, timeout=15)
        try:
            connection.request("POST", "/v1/chat/completions", json.dumps({
                "model": "mock-model", "messages": [{"role": "user", "content": "unit request"}],
            }), {"Content-Type": "application/json", "Authorization": "Bearer parallel-test-token",
                 "X-LineageWeave-Session-Id": "same-private-session"})
            with connection.getresponse() as response:
                assert response.status == 502
                return json.loads(response.read())["error"]["detail"]["request_id"]
        finally:
            connection.close()

    with caplog.at_level("DEBUG"):
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(send_request) for _ in range(2)]
                request_ids = [future.result(timeout=20) for future in futures]
            assert len(overlapping_threads) == 2
            assert len(set(request_ids)) == 2
            provider_logs = [row.getMessage() for row in caplog.records
                             if row.getMessage().startswith(("provider_attempt ", "provider_attempt_failed "))]
            assert len(provider_logs) == 4
            for request_id in request_ids:
                matching = [message for message in provider_logs if f"request_id={request_id}" in message]
                assert len(matching) == 2
                assert sum(message.startswith("provider_attempt ") for message in matching) == 1
            assert "same-private-session" not in "\n".join(provider_logs)
        finally:
            server.shutdown()
            server_thread.join(timeout=5)
            server.server_close()
            router.close()


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
    import urllib.request

    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    thread = _start_test_server(server)
    port = server.server_address[1]
    with caplog.at_level("INFO", logger="contextual_orchestrator.server"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
                assert response.status == 200
            _wait_for_caplog(caplog, lambda text: "http_request" in text)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    assert "http_request" in caplog.text
    assert "method=GET" in caplog.text
    assert "path=/healthz" in caplog.text
    assert "status=200" in caplog.text
    import re
    summary_lines = [row.getMessage() for row in caplog.records
                     if row.getMessage().startswith("http_request ")]
    assert len(summary_lines) == 1
    assert re.search(r" request_id=[0-9a-f]{32}$", summary_lines[0])


def test_per_request_info_summary_never_includes_query_string(caplog):
    """The INFO per-request summary logs the bare path only, never a query string.

    A caller could plausibly put a token in a query parameter (a common
    client habit) even though this server's own auth is header-only; the
    summary line's own docstring already claims to be body-free and never
    carry "a query string beyond the raw path", so the raw query string
    (and anything in it) must never reach this log line.
    """
    import threading
    import urllib.request

    fake_token = "sk-FAKEFAKEFAKEFAKEFAKEQUERYSTRING123"
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    thread = _start_test_server(server)
    port = server.server_address[1]
    with caplog.at_level("INFO", logger="contextual_orchestrator.server"):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/healthz?api_key={fake_token}", timeout=5
            ) as response:
                assert response.status == 200
            _wait_for_caplog(caplog, lambda text: "http_request" in text)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

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

    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    thread = _start_test_server(server)
    port = server.server_address[1]
    connection = None
    with caplog.at_level("INFO", logger="contextual_orchestrator.server"):
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", "/healthz")
            with connection.getresponse() as response:
                assert response.status == 200
                response.read()
                _wait_for_caplog(caplog, lambda text: "http_request" in text)
            connection.close()  # keep-alive connection closed with no second request
        finally:
            if connection is not None:
                connection.close()
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

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

    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    thread = _start_test_server(server)
    port = server.server_address[1]
    connection = None
    with caplog.at_level("INFO", logger="contextual_orchestrator.server"):
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("PUT", "/healthz")  # no do_PUT -- stdlib's own 501 path
            with connection.getresponse() as response:
                assert response.status == 501
                response.read()
                _wait_for_caplog(caplog, lambda text: "http_request" in text)
        finally:
            if connection is not None:
                connection.close()
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    assert "http_request" in caplog.text
    assert "status=501" in caplog.text


def test_malformed_request_line_is_captured_in_log(caplog):
    """A malformed request line that still got a real response is not silently skipped.

    ``BaseHTTPRequestHandler.parse_request`` rejects an unparsable request
    line via ``send_error`` -- captured by the ``send_response`` override
    into ``_last_status`` -- *before* ``self.command``/``self.path`` are
    ever assigned: stdlib's own ``parse_request`` explicitly resets
    ``self.command`` to ``None`` "in case of error on the first line" and
    only reaches the later assignment that would set ``path`` once parsing
    succeeds. The per-request summary's old "nothing to report" guard only
    checked method/path, so a connection that *did* deliver real bytes and
    *did* get a real 400 response left no log trace at all -- indistinguishable,
    from the log's perspective, from a keep-alive connection closing with
    zero bytes (see ``test_keep_alive_close_does_not_log_phantom_request``,
    which must stay silent).
    """
    import socket
    import threading

    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    thread = _start_test_server(server)
    port = server.server_address[1]
    with caplog.at_level("INFO", logger="contextual_orchestrator.server"):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
                # A single-token request line: too few words for
                # parse_request's `2 <= len(words) <= 3` shape check, so it
                # calls send_error(400, ...) without ever assigning
                # self.command/self.path. A request line this malformed never
                # reaches the branch that promotes `self.request_version`
                # past stdlib's own "HTTP/0.9" default, so `send_error`'s
                # underlying `send_response_only`/`send_header` calls
                # deliberately write no status line or headers at all (a
                # documented stdlib quirk for an unparsable first line) --
                # only the HTML error body reaches the wire. The 400 is still
                # real: it is what `send_response` records into
                # `_last_status`, which is what this test is actually about.
                connection.sendall(b"GARBAGE\r\n\r\n")
                response = b""
                while True:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    response += chunk
            assert b"400" in response
            _wait_for_caplog(caplog, lambda text: "http_request" in text)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    assert "http_request" in caplog.text
    assert "status=400" in caplog.text


def test_per_request_info_summary_absent_below_info(caplog):
    import threading
    import urllib.request

    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    thread = _start_test_server(server)
    port = server.server_address[1]
    with caplog.at_level("WARNING", logger="contextual_orchestrator.server"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
                assert response.status == 200
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

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


def test_readiness_probe_uses_separate_operation_telemetry(monkeypatch):
    """A startup readiness probe cannot masquerade as a caller request attempt."""
    captured = []

    @contextmanager
    def capture(name, attributes):
        captured.append((name, attributes))
        yield None

    client = ModelClient()
    agent = ModelAgent(
        "provider_agent",
        "model-x",
        base_url="https://provider.example/v1",
        credential_key="",
        provider_name="openai",
        group_name="model-family-x",
    )
    monkeypatch.setattr(orchestrator_module, "traced", capture)
    monkeypatch.setattr(client, "_validate_provider", lambda unused_agent: None)
    monkeypatch.setattr(
        client, "_send_raw_with_retry", lambda *_args, **_kwargs: {"ok": True}
    )

    assert client.probe_structured_chat(agent, {"messages": []}) == {"ok": True}
    assert captured[0][0] == "capability_probe.chat model-x"
    assert captured[0][1]["contextual_orchestrator.operation_kind"] == "capability_probe"
    assert captured[0][1]["contextual_orchestrator.model_group"] == "model_family_x"
    assert captured[0][1]["contextual_orchestrator.fallback_outcome"] == "not_attempted"


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
    span.set_attribute.assert_any_call("error.type", "provider_connection_error")
    span.set_attribute.assert_any_call(
        "contextual_orchestrator.error_summary",
        "provider_connection_error",
    )
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


def test_traced_logs_actionable_bounded_failure_evidence(monkeypatch, caplog):
    """Operators get a safe cause, model group, status, and fallback outcome."""
    import urllib.error

    tracer = MagicMock()
    span = tracer.start_as_current_span.return_value.__enter__.return_value
    monkeypatch.setattr(telemetry_module.trace, "get_tracer", lambda unused_name: tracer)
    message = (
        "'messages' must contain the word 'json' in some form, to use "
        "'response_format' of type 'json_object'.No fallback model group found; "
        "customer-private-text"
    )
    body = io.BytesIO(json.dumps({"error": {"message": message}}).encode())

    with pytest.raises(urllib.error.HTTPError):
        with traced(
            "capability_probe.chat gpt-4.1",
            {
                "contextual_orchestrator.model_group": "gpt-4.1",
                "contextual_orchestrator.fallback_outcome": "not_attempted",
            },
        ):
            raise urllib.error.HTTPError("https://private.example", 400, "bad", None, body)

    span.set_attribute.assert_any_call("error.type", "invalid_request_error")
    span.set_attribute.assert_any_call("contextual_orchestrator.provider_status_code", 400)
    span.set_attribute.assert_any_call(
        "contextual_orchestrator.error_summary",
        "messages must mention json when response_format is json_object",
    )
    assert "provider_status=400" in caplog.text
    assert "model_group=gpt-4.1" in caplog.text
    assert "fallback_outcome=not_attempted" in caplog.text
    assert "messages must mention json when response_format is json_object" in caplog.text
    assert "No fallback model group" not in caplog.text
    assert "customer-private-text" not in caplog.text
    assert "private.example" not in caplog.text


def test_traced_recognizes_litellm_prefixed_json_object_diagnostic(
    monkeypatch, caplog
):
    """A gateway prefix cannot hide Azure's actionable JSON-object contract."""
    import urllib.error

    tracer = MagicMock()
    span = tracer.start_as_current_span.return_value.__enter__.return_value
    monkeypatch.setattr(telemetry_module.trace, "get_tracer", lambda unused_name: tracer)
    message = (
        "AzureException BadRequestError - 'messages' must contain the word 'json' "
        "in some form, to use 'response_format' of type 'json_object'."
        "No fallback model group found; customer-private-text"
    )
    body = io.BytesIO(json.dumps({"error": {"message": message}}).encode())

    with pytest.raises(urllib.error.HTTPError):
        with traced(
            "capability_probe.chat gpt-4.1",
            {"contextual_orchestrator.model_group": "gpt-4.1"},
        ):
            raise urllib.error.HTTPError("https://private.example", 400, "bad", None, body)

    span.set_attribute.assert_any_call(
        "contextual_orchestrator.error_summary",
        "messages must mention json when response_format is json_object",
    )
    assert "provider_status=400" in caplog.text
    assert "model_group=gpt-4.1" in caplog.text
    assert "AzureException" not in caplog.text
    assert "No fallback model group" not in caplog.text
    assert "customer-private-text" not in caplog.text
    assert "private.example" not in caplog.text


def test_traced_does_not_export_natural_language_provider_echo(monkeypatch, caplog):
    """Unstructured provider prose is never evidence that request text is absent."""
    import urllib.error

    tracer = MagicMock()
    span = tracer.start_as_current_span.return_value.__enter__.return_value
    monkeypatch.setattr(telemetry_module.trace, "get_tracer", lambda unused_name: tracer)
    echoed = "The supplied phrase customer-private-text is not valid JSON"
    body = io.BytesIO(json.dumps({"error": {"message": echoed}}).encode())

    with pytest.raises(urllib.error.HTTPError):
        with traced("capability_probe.chat model-x"):
            raise urllib.error.HTTPError("https://private.example", 400, "bad", None, body)

    span.set_attribute.assert_any_call(
        "contextual_orchestrator.error_summary", "invalid_request_error"
    )
    assert echoed not in caplog.text
    assert "customer-private-text" not in caplog.text


def test_traced_does_not_export_classified_provider_prose(monkeypatch, caplog):
    """A previously classified provider error cannot bypass the summary allowlist."""
    from contextual_orchestrator.provider_errors import ProviderUpstreamError

    tracer = MagicMock()
    span = tracer.start_as_current_span.return_value.__enter__.return_value
    monkeypatch.setattr(telemetry_module.trace, "get_tracer", lambda unused_name: tracer)
    echoed = "The supplied phrase customer-private-text is invalid"
    error = ProviderUpstreamError(
        agent_id="provider_agent",
        model="model-x",
        error_code="invalid_request_error",
        message=echoed,
        client_status=400,
        provider_status=400,
    )

    with pytest.raises(ProviderUpstreamError):
        with traced("chat model-x"):
            raise error

    span.set_attribute.assert_any_call(
        "contextual_orchestrator.error_summary", "invalid_request_error"
    )
    assert echoed not in caplog.text
    assert "customer-private-text" not in caplog.text


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
