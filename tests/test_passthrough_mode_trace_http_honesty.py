"""Gateway mode and trace knobs must fail closed on tools passthrough.

``_validate_mode`` and ``include_orchestration_trace`` live after the tools /
``response_format`` early return. An OpenAI SDK tool-calling body can therefore
bill a single-agent completion while sending ``mode=conduct``, ``mode=bogus``,
or ``include_orchestration_trace=true`` / ``\"yes\"``. Passthrough has no
workflow or trace plane — those knobs must 400, not silently drop.

OpenAI. (2024). *Create chat completion*. OpenAI API reference.
https://platform.openai.com/docs/api-reference/chat/create
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

_TEST_AUTH_TOKEN = "passthrough_mode_trace_http_honesty_token"  # noqa: S105

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


def _post(port: int, payload: dict) -> tuple[int, dict | str]:
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
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_tools_rejects_bogus_mode() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "mode": "bogus",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_mode" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_conduct_mode() -> None:
    """Conduct is a multi-agent workflow; tools proxy is single-agent only."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "mode": "conduct",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_mode" in blob
        assert "conduct" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_non_boolean_include_orchestration_trace() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "include_orchestration_trace": "yes",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_include_orchestration_trace" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_include_orchestration_trace_true() -> None:
    """Passthrough cannot return a workflow trace — true must not bill silently."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "include_orchestration_trace": True,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_include_orchestration_trace" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_route_mode_and_trace_false() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "mode": "route",
                "include_orchestration_trace": False,
            },
        )
        assert status == 200, body
        assert isinstance(body, dict)
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_tools_rejects_bogus_mode()
    test_http_chat_tools_rejects_conduct_mode()
    test_http_chat_tools_rejects_non_boolean_include_orchestration_trace()
    test_http_chat_tools_rejects_include_orchestration_trace_true()
    test_http_chat_tools_accepts_route_mode_and_trace_false()
    print("ok")
