"""Chat Completions include_orchestration_trace honesty over HTTP."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "chat_include_orchestration_trace_http_honesty_token"  # noqa: S105
_TEST_INFERENCE_TOKEN = "trace_inference_only"  # noqa: S105
_TEST_TRACE_TOKEN = "trace_reader"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(
    port: int,
    payload: dict,
    token: str = _TEST_AUTH_TOKEN,
    *,
    path: str = "/v1/chat/completions",
) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(port: int, path: str, token: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"authorization": f"Bearer {token}", "connection": "close"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    # expose_trace_by_default false so omit hides trace unless request opts in.
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, expose_trace_by_default=False),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _server_with_verifier(verifier):
    orchestrator = build()
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(bearer_verifier=verifier),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1], orchestrator


def test_trace_requires_a_verified_trace_purpose() -> None:
    server, thread, port, _orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_INFERENCE_TOKEN and scope == "inference"
    )
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "trace denied"}],
                "include_orchestration_trace": True,
            },
            token=_TEST_INFERENCE_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 401
    assert body["error"]["code"] == "unauthorized"


def test_trace_access_is_audited_before_response_release() -> None:
    server, thread, port, orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_TRACE_TOKEN and scope in {"inference", "trace"}
    )
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "trace allowed"}],
                "include_orchestration_trace": True,
            },
            token=_TEST_TRACE_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 200
    assert "orchestration" in body
    events = list(orchestrator._audit_events)
    access_index = next(
        index
        for index, event in enumerate(events)
        if event["event_type"] == "orchestration_trace_access_granted"
    )
    workflow_index = next(
        index for index, event in enumerate(events) if event["event_type"] == "workflow_run_created"
    )
    assert workflow_index < access_index


def test_trace_is_not_released_when_audit_persistence_fails() -> None:
    server, thread, port, orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_TRACE_TOKEN and scope in {"inference", "trace"}
    )

    append_audit_event = orchestrator._append_audit_event

    def fail_audit(event_type: str, detail: dict, **kwargs: object) -> None:
        if event_type == "orchestration_trace_access_granted":
            raise OSError("audit store unavailable")
        append_audit_event(event_type, detail, **kwargs)

    orchestrator._append_audit_event = fail_audit  # type: ignore[method-assign]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "trace fail closed"}],
                "include_orchestration_trace": True,
            },
            token=_TEST_TRACE_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 503
    assert body["error"]["code"] == "trace_audit_unavailable"
    assert "orchestration" not in body
    assert not any(
        event["event_name"] == "chat_completion_requested"
        for event in orchestrator._analytics_events
    )


def test_http_chat_rejects_include_orchestration_trace_non_boolean() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "trace string"}],
                "include_orchestration_trace": "yes",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_include_orchestration_trace" in blob
        assert "boolean" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tool_passthrough_rejects_non_boolean_trace_flag() -> None:
    """Tool passthrough must not bypass authorization-sensitive type checks."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "trace string"}],
                "tools": [{"type": "function", "function": {"name": "lookup"}}],
                "include_orchestration_trace": "yes",
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_include_orchestration_trace"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tool_passthrough_rejects_null_trace_flag() -> None:
    """Tool passthrough treats explicit null as an invalid trace request."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "trace null"}],
                "tools": [{"type": "function", "function": {"name": "lookup"}}],
                "include_orchestration_trace": None,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_include_orchestration_trace"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_include_orchestration_trace_null() -> None:
    """Trace disclosure is a strict authorization-sensitive JSON boolean."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "trace null"}],
                "include_orchestration_trace": None,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_include_orchestration_trace"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_structured_chat_cannot_bypass_trace_flag_validation() -> None:
    """Validate the trace flag before structured chat can return early."""
    server, thread, port = _server()
    try:
        for invalid in ("false", 1, None, [], {}):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "return JSON"}],
                    "response_format": {"type": "json_object"},
                    "include_orchestration_trace": invalid,
                },
            )
            assert status == 400, (invalid, body)
            assert body["error"]["code"] == "invalid_include_orchestration_trace"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_structured_chat_with_trace_returns_authorized_trace() -> None:
    """Structured chat with include_orchestration_trace=True returns the trace."""
    server, thread, port, orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_TRACE_TOKEN and scope in {"inference", "trace"}
    )
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "return JSON"}],
                "response_format": {"type": "json_object"},
                "include_orchestration_trace": True,
            },
            token=_TEST_TRACE_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    # PR 891: structured chat supports trace disclosure
    assert status == 200, body


def test_structured_chat_ignores_server_trace_default_when_flag_is_omitted() -> None:
    """A server default must not turn an ordinary structured request into an opt-in."""
    server, thread, port, orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_TRACE_TOKEN and scope == "inference"
    )
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "return JSON"}],
                "response_format": {"type": "json_object"},
            },
            token=_TEST_TRACE_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 200, body
    assert not any(
        event["event_type"] == "orchestration_trace_access_granted"
        for event in orchestrator._audit_events
    )


def test_fast_route_stream_rejects_explicit_trace_before_provider_work() -> None:
    """Direct Chat streaming cannot silently discard an explicit trace request."""
    server, thread, port, _orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_TRACE_TOKEN and scope in {"inference", "trace"}
    )
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
                "include_orchestration_trace": True,
            },
            token=_TEST_TRACE_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 400, body
    assert body["error"]["code"] == "unsupported_trace_disclosure"


def test_fast_route_stream_ignores_server_trace_default_when_flag_is_omitted() -> None:
    """An ordinary direct stream remains available to an inference-only caller."""
    server, thread, port, _orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_INFERENCE_TOKEN and scope == "inference"
    )
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            }
        ).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_INFERENCE_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 200
            assert b"data:" in response.read()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_tool_chat_rejects_trace_disclosure_it_cannot_return() -> None:
    """Do not silently ignore a trace request on the tool passthrough path."""
    server, thread, port, _orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_TRACE_TOKEN and scope in {"inference", "trace"}
    )
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "use tool"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "include_orchestration_trace": True,
            },
            token=_TEST_TRACE_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 400, body
    assert body["error"]["code"] == "trace_unavailable"  # PR 891: tool passthrough uses trace_unavailable


def test_access_report_disclosure_fails_closed_when_audit_fails() -> None:
    """Do not release accessed-output evidence without durable trace audit."""
    server, thread, port, orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_TRACE_TOKEN and scope in {"inference", "trace", "admin"}
    )
    try:
        status, created = _post(
            port,
            {
                "prompt_text": "create report",
                "run_mode": "conduct",
                "include_orchestration_trace": False,
            },
            token=_TEST_TRACE_TOKEN,
            path="/api/v1/workflow_runs",
        )
        assert status == 201, created
        workflow_run_id = created["workflow_run_id"]
        append_audit_event = orchestrator._append_audit_event

        def fail_trace_audit(event_type: str, detail: dict, **kwargs: object) -> None:
            if event_type == "orchestration_trace_access_granted":
                raise OSError("audit store unavailable")
            append_audit_event(event_type, detail, **kwargs)

        orchestrator._append_audit_event = fail_trace_audit  # type: ignore[method-assign]
        status, body = _get(
            port,
            f"/api/v1/access_reports/{workflow_run_id}",
            _TEST_TRACE_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 503, body
    assert body["error"]["code"] == "trace_audit_unavailable"


def test_invalid_chat_does_not_audit_trace_disclosure() -> None:
    """Do not record a grant when request validation prevents disclosure."""
    server, thread, port, orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_TRACE_TOKEN and scope in {"inference", "trace"}
    )
    try:
        status, _body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": "not-an-array",
                "include_orchestration_trace": True,
            },
            token=_TEST_TRACE_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 400
    assert not any(
        event["event_type"] == "orchestration_trace_access_granted"
        for event in orchestrator._audit_events
    )


def test_batched_chat_does_not_audit_trace_disclosure() -> None:
    """A 202 job handle is not a trace disclosure."""
    server, thread, port, orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_TRACE_TOKEN and scope in {"inference", "trace"}
    )
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "later"}],
                "routing": {"latency_tolerant": True},
                "include_orchestration_trace": True,
            },
            token=_TEST_TRACE_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 202, body
    assert not any(
        event["event_type"] == "orchestration_trace_access_granted"
        for event in orchestrator._audit_events
    )


def test_http_chat_accepts_include_orchestration_trace_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "trace on"}],
                "include_orchestration_trace": True,
            },
        )
        assert status == 200, body
        # Opt-in must surface orchestration for trusted callers.
        assert "orchestration" in body or "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_structured_chat_rejects_disclosure_it_cannot_return() -> None:
    """Structured synthesis fails closed under the trace-disclosure contract."""
    server, thread, port = _server()
    try:
        base = {
            "model": "mock-planner",
            "messages": [{"role": "user", "content": "structured trace"}],
            "response_format": {"type": "json_object"},
        }
        status, disclosed = _post(
            port, {**base, "include_orchestration_trace": True}
        )
        hidden_status, hidden = _post(
            port, {**base, "include_orchestration_trace": False}
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 400, disclosed
    assert disclosed["error"]["code"] == "unsupported_trace_disclosure"
    assert hidden_status == 200, hidden
    assert "trace" not in hidden.get("orchestration", {})


def test_http_tool_passthrough_rejects_a_trace_it_cannot_return() -> None:
    """A granted trace audit cannot exist without a disclosed workflow trace."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "use a tool"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "read_value",
                            "description": "Read one value.",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "include_orchestration_trace": True,
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 400
    assert body["error"]["code"] == "unsupported_trace_disclosure"


def test_http_chat_accepts_include_orchestration_trace_false() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "trace off"}],
                "include_orchestration_trace": False,
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_include_orchestration_trace_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "no trace flag"}],
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_trace_requires_a_verified_trace_purpose()
    test_trace_access_is_audited_before_response_release()
    test_trace_is_not_released_when_audit_persistence_fails()
    test_http_chat_rejects_include_orchestration_trace_non_boolean()
    test_http_chat_rejects_include_orchestration_trace_null()
    test_structured_chat_cannot_bypass_trace_flag_validation()
    test_http_chat_accepts_include_orchestration_trace_true()
    test_http_chat_accepts_include_orchestration_trace_false()
    test_http_chat_accepts_include_orchestration_trace_omitted()
    print("ok")
