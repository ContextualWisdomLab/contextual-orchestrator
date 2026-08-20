"""message weight digit-string and tool.function.strict bool coerce over HTTP."""

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

_TEST_AUTH_TOKEN = "weight_strict_bool_coerce_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
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
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_message_weight_digit_strings() -> None:
    server, thread, port = _server()
    try:
        for val in ("0", "1", "0.0", "1.0", " 1 ", 0, 1, 0.0, 1.0):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [
                        {"role": "user", "content": f"weight {val!r}", "weight": val}
                    ],
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_message_weight_out_of_range() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "weight 2", "weight": "2"}],
            },
        )
        assert status == 400, body
        assert "invalid_message_weight" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_strict_bool_coerce_forms() -> None:
    server, thread, port = _server()
    try:
        for val in (True, False, 0, 1, 0.0, 1.0, "true", "false", "0", "1", "0.0", "1.0"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"strict {val!r}"}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "f",
                                "parameters": {"type": "object"},
                                "strict": val,
                            },
                        }
                    ],
                },
            )
            assert status == 422, (val, body)
            assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_message_prefix_false_coerce_forms() -> None:
    server, thread, port = _server()
    try:
        for val in (False, 0, 0.0, "false", "0", "0.0"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [
                        {"role": "user", "content": f"prefix {val!r}", "prefix": val}
                    ],
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_message_prefix_true() -> None:
    server, thread, port = _server()
    try:
        for val in (True, 1, "true", "1.0"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [
                        {"role": "user", "content": f"prefix bad {val!r}", "prefix": val}
                    ],
                },
            )
            assert status == 400, (val, body)
            assert "invalid_message_prefix" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_message_weight_digit_strings()
    test_http_chat_still_rejects_message_weight_out_of_range()
    test_http_chat_accepts_tool_strict_bool_coerce_forms()
    test_http_chat_accepts_message_prefix_false_coerce_forms()
    test_http_chat_still_rejects_message_prefix_true()
    print("ok")
