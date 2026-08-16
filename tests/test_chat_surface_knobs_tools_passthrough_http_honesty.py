"""Tools passthrough must fail-closed on store and surface knobs.

``store``, ``modalities``, ``prediction``, ``reasoning_effort``,
``service_tier``, and ``metadata`` are validated on the orchestration path
only. SDK tool-calling bodies that send those fields still reach
``proxy_completion`` and bill a sync completion. Named errors must match
the orchestration path.

OpenAI. (n.d.). *Chat Completions API*.
https://platform.openai.com/docs/api-reference/chat/create

Sakana AI. (2026, June 22). *Sakana Fugu: One Model to Command Them All*.
https://sakana.ai/fugu-release/
"""

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

_TEST_AUTH_TOKEN = "chat_surface_knobs_tools_passthrough_token"  # noqa: S105

_LOOKUP_TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup_balance", "parameters": {"type": "object"}},
    }
]


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _tools_body(**extra: object) -> dict:
    payload: dict = {
        "model": "mock-planner",
        "messages": [{"role": "user", "content": "look up the invoice"}],
        "tools": _LOOKUP_TOOLS,
    }
    payload.update(extra)
    return payload


def test_http_chat_rejects_store_true_with_tools() -> None:
    """Buyer asked to persist the completion; tools path must not bill without store."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(store=True))
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_store" in blob
        assert "not supported" in blob
        assert "chat" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_store_false_with_tools() -> None:
    """Explicit no-store is an honest no-op on tools passthrough."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(store=False))
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_null_store_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(store=None))
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_audio_modalities_with_tools() -> None:
    """Text gateway must not bill a tools call as if audio output was applied."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(modalities=["audio"]))
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_modalities" in blob
        assert "text" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_text_modalities_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(modalities=["text"]))
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_prediction_with_tools() -> None:
    """Predicted Outputs are not applied; do not bill a predicted tools proxy."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _tools_body(prediction={"type": "content", "content": "INV-1001"}),
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_prediction" in blob
        assert "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_null_prediction_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(prediction=None))
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_high_reasoning_effort_with_tools() -> None:
    """o-series reasoning_effort is not threaded into the tools proxy."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(reasoning_effort="high"))
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_reasoning_effort" in blob
        assert "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_none_reasoning_effort_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(reasoning_effort="none"))
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_flex_service_tier_with_tools() -> None:
    """No tiered capacity plane; flex must not bill as priority processing."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(service_tier="flex"))
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_service_tier" in blob
        assert "chat" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_auto_service_tier_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(service_tier="auto"))
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_string_metadata_with_tools() -> None:
    """Cost/observability consumers must not receive untyped metadata junk."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(metadata={"invoice_id": 1001}))
        assert status == 400, body
        assert "invalid_metadata" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_string_metadata_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(metadata={"invoice_id": "INV-1001"}))
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_store_true_with_response_format() -> None:
    """json_object passthrough uses the same early-return as tools."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "response_format": {"type": "json_object"},
                "store": True,
            },
        )
        assert status == 400, body
        assert "invalid_store" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_store_true_with_tools()
    test_http_chat_accepts_store_false_with_tools()
    test_http_chat_accepts_null_store_with_tools()
    test_http_chat_rejects_audio_modalities_with_tools()
    test_http_chat_accepts_text_modalities_with_tools()
    test_http_chat_rejects_prediction_with_tools()
    test_http_chat_accepts_null_prediction_with_tools()
    test_http_chat_rejects_high_reasoning_effort_with_tools()
    test_http_chat_accepts_none_reasoning_effort_with_tools()
    test_http_chat_rejects_flex_service_tier_with_tools()
    test_http_chat_accepts_auto_service_tier_with_tools()
    test_http_chat_rejects_non_string_metadata_with_tools()
    test_http_chat_accepts_string_metadata_with_tools()
    test_http_chat_rejects_store_true_with_response_format()
    print("ok")
