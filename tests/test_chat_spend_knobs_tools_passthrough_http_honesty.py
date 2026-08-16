"""Tools passthrough must fail-closed on spend knobs and batch hints.

``seed``, penalties, ``max_tokens`` / ``max_completion_tokens``, ``n``, and
batch routing hints are validated on the orchestration path only. SDK
tool-calling bodies that send those fields still reach ``proxy_completion``
and bill a sync completion. Named errors must match the orchestration path.

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

_TEST_AUTH_TOKEN = "chat_spend_knobs_tools_passthrough_token"  # noqa: S105

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


def test_http_chat_rejects_seed_with_tools() -> None:
    """Chat does not apply seed; tools bodies must not bill a seeded proxy."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(seed=42))
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_seed" in blob
        assert "not supported" in blob
        assert "chat" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_null_seed_with_tools() -> None:
    """SDK optional default null seed remains an omit-equivalent no-op."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(seed=None))
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_out_of_range_presence_penalty_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(presence_penalty=3))
        assert status == 400, body
        assert "invalid_presence_penalty" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_out_of_range_frequency_penalty_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(frequency_penalty=3))
        assert status == 400, body
        assert "invalid_frequency_penalty" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_in_range_penalties_with_tools() -> None:
    """Valid penalties are forwarded; do not fail-closed on in-range values."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _tools_body(presence_penalty=0.5, frequency_penalty=-0.25),
        )
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_zero_max_tokens_with_tools() -> None:
    """Zero budget must not bill a completion on the tools path."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(max_tokens=0))
        assert status == 400, body
        assert "invalid_max_tokens" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_zero_max_completion_tokens_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(max_completion_tokens=0))
        assert status == 400, body
        assert "invalid_max_completion_tokens" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_positive_max_tokens_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(max_tokens=16))
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_n_gt1_with_tools() -> None:
    """Buyer asked for three choices; tools path must not return one billed choice."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(n=3))
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_n" in blob
        assert "not supported" in blob
        assert "chat" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_n_one_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(n=1))
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_batch_channel_with_tools() -> None:
    """Tools passthrough is sync proxy; do not bill batch as a sync completion."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(routing={"channel": "batch"}))
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_routing" in blob
        assert "batch" in blob
        assert "tools" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_latency_tolerant_true_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(routing={"latency_tolerant": True}))
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_routing" in blob
        assert "latency_tolerant" in blob
        assert "tools" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_sync_routing_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_body(routing={"channel": "sync"}))
        assert status == 200, body
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_seed_with_tools()
    test_http_chat_accepts_null_seed_with_tools()
    test_http_chat_rejects_out_of_range_presence_penalty_with_tools()
    test_http_chat_rejects_out_of_range_frequency_penalty_with_tools()
    test_http_chat_accepts_in_range_penalties_with_tools()
    test_http_chat_rejects_zero_max_tokens_with_tools()
    test_http_chat_rejects_zero_max_completion_tokens_with_tools()
    test_http_chat_accepts_positive_max_tokens_with_tools()
    test_http_chat_rejects_n_gt1_with_tools()
    test_http_chat_accepts_n_one_with_tools()
    test_http_chat_rejects_batch_channel_with_tools()
    test_http_chat_rejects_latency_tolerant_true_with_tools()
    test_http_chat_accepts_sync_routing_with_tools()
    print("ok")
