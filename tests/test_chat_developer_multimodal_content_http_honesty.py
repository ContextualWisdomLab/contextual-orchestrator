"""Chat message content honesty: developer role and multimodal arrays fail-closed."""

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

_TEST_AUTH_TOKEN = "chat_message_content_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_string_content() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "plain text invoice note"}],
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_developer_role() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "developer", "content": "system-like instructions"},
                    {"role": "user", "content": "hi"},
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_role" in blob
        assert "developer" in blob
        assert "system" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_multipart_image_content() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "describe this receipt"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://example.com/receipt.png"},
                            },
                        ],
                    }
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_content" in blob
        assert "multipart" in blob or "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_input_audio_content_part() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {"data": "AAAA", "format": "wav"},
                            }
                        ],
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_string_non_array_content() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": 12345}],
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in json.dumps(body) or "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_string_content()
    test_http_chat_rejects_developer_role()
    test_http_chat_rejects_multipart_image_content()
    test_http_chat_rejects_input_audio_content_part()
    test_http_chat_rejects_non_string_non_array_content()
    print("ok")
