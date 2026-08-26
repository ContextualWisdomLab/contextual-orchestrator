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


def _post(port: int, payload: dict, token: str = _TEST_AUTH_TOKEN) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
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
    assert access_index < workflow_index


def test_trace_is_not_released_when_audit_persistence_fails() -> None:
    server, thread, port, orchestrator = _server_with_verifier(
        lambda token, scope: token == _TEST_TRACE_TOKEN and scope in {"inference", "trace"}
    )

    def fail_audit(_event_type: str, _detail: dict) -> None:
        raise OSError("audit store unavailable")

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


def test_http_structured_chat_discloses_only_an_authorized_conduct_trace() -> None:
    """Structured synthesis preserves the same audited trace contract."""
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

    assert status == hidden_status == 200
    trace = disclosed["orchestration"]["trace"]
    assert len(trace) >= 2
    assert trace[-1]["role"] == "synthesizer"
    assert "trace" not in hidden["orchestration"]


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
    test_http_chat_accepts_include_orchestration_trace_true()
    test_http_chat_accepts_include_orchestration_trace_false()
    test_http_chat_accepts_include_orchestration_trace_omitted()
    print("ok")
