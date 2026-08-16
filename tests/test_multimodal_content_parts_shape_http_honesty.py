"""Multimodal content-part shape honesty (empty text/url, string image_url, detail)."""

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

_TEST_AUTH_TOKEN = "multimodal_content_parts_shape_http_honesty_token"  # noqa: S105


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


def _error_blob(body: dict) -> str:
    return json.dumps(body)


def test_http_chat_rejects_empty_text_content_part() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": ""}],
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in _error_blob(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_whitespace_text_content_part() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "   "}],
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in _error_blob(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_empty_image_url() -> None:
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
                                "type": "image_url",
                                "image_url": {"url": ""},
                            }
                        ],
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in _error_blob(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_bare_string_image_url() -> None:
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
                            {"type": "text", "text": "caption this"},
                            {
                                "type": "image_url",
                                "image_url": "https://example.com/photo.png",
                            },
                        ],
                    }
                ],
            },
        )
        assert status == 200, body
        assert body.get("object") == "chat.completion" or "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_image_url_detail_high() -> None:
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
                            {"type": "text", "text": "zoom"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "https://example.com/photo.png",
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_invalid_image_url_detail() -> None:
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
                                "type": "image_url",
                                "image_url": {
                                    "url": "https://example.com/photo.png",
                                    "detail": "ultra",
                                },
                            }
                        ],
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in _error_blob(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_omits_null_image_url_detail() -> None:
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
                            {"type": "text", "text": "see"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "https://example.com/photo.png",
                                    "detail": None,
                                },
                            },
                        ],
                    }
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_empty_text_content_part()
    test_http_chat_rejects_whitespace_text_content_part()
    test_http_chat_rejects_empty_image_url()
    test_http_chat_accepts_bare_string_image_url()
    test_http_chat_accepts_image_url_detail_high()
    test_http_chat_rejects_invalid_image_url_detail()
    test_http_chat_omits_null_image_url_detail()
    print("ok")
