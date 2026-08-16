"""Tools passthrough must fail-closed on attribution and routing before proxy.

``_validate_attribution`` and ``_validate_routing`` live after the tools /
``response_format`` early return. An OpenAI SDK tool-calling body can therefore
bill a sync completion while sending an unknown spend dimension, or while
asking for ``routing.channel=batch`` / ``latency_tolerant=true``. Tools
passthrough has no batch job plane — those hints must 400, not silently
sync-proxy.

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

_TEST_AUTH_TOKEN = "passthrough_attribution_routing_http_honesty_token"  # noqa: S105

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


def test_http_chat_tools_rejects_unknown_attribution_dimension() -> None:
    """Unknown spend dimensions must not smuggle through tools passthrough."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "attribution": {"team": "platform", "cost_center": "xyz"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_attribution" in blob
        assert "unsupported" in blob or "cost_center" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_attribution_non_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "attribution": "team=platform",
            },
        )
        assert status == 400, body
        assert "invalid_attribution" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_routing_unknown_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "routing": {"channel": "sync", "region": "us-east"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_routing" in blob
        assert "unsupported" in blob or "region" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_batch_channel() -> None:
    """Tools passthrough has no batch job plane — do not bill a silent sync."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "routing": {"channel": "batch"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_routing" in blob
        assert "batch" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_latency_tolerant_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "routing": {"latency_tolerant": True},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_routing" in blob
        assert "latency_tolerant" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_response_format_rejects_unknown_attribution() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "return json"}],
                "response_format": {"type": "json_object"},
                "attribution": {"cost_center": "xyz"},
            },
        )
        assert status == 400, body
        assert "invalid_attribution" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_known_sync_attribution_and_routing() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "attribution": {"team": "platform", "company": "acme"},
                "routing": {"channel": "sync", "priority": "interactive"},
            },
        )
        assert status == 200, body
        assert isinstance(body, dict) and "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_unknown_stream_options_key_even_when_null() -> None:
    """Unknown-null stream_options must 400 on the billed tools path too."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "invoice lookup"}],
                "tools": _LOOKUP_TOOLS,
                "stream_options": {"include_continuous": None},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream_options" in blob
        assert "include_continuous" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_tools_rejects_unknown_attribution_dimension()
    test_http_chat_tools_rejects_attribution_non_object()
    test_http_chat_tools_rejects_routing_unknown_key()
    test_http_chat_tools_rejects_batch_channel()
    test_http_chat_tools_rejects_latency_tolerant_true()
    test_http_chat_response_format_rejects_unknown_attribution()
    test_http_chat_tools_accepts_known_sync_attribution_and_routing()
    test_http_chat_tools_rejects_unknown_stream_options_key_even_when_null()
    print("ok")
