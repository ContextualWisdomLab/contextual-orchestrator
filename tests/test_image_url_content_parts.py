"""OpenAI image_url content parts on chat messages force vision passthrough."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _message_has_image_content,
    _normalize_message_content,
    build_server,
)

_TEST_AUTH_TOKEN = "img_url_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_normalize_and_detect_image_parts() -> None:
    assert _normalize_message_content("hi") == "hi"
    assert _normalize_message_content(
        [{"type": "text", "text": "what is this?"}, {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}]
    ) == "what is this?"
    assert _normalize_message_content(
        [{"type": "image_url", "image_url": {"url": "https://example.com/a.png", "detail": "low"}}]
    ) == "[image]"
    assert _message_has_image_content(
        [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://x/y"}}]}]
    )
    try:
        _normalize_message_content(
            [{"type": "image_url", "image_url": {"url": ""}}]
        )
        raise AssertionError("expected invalid empty url")
    except RequestError as exc:
        assert exc.code == "invalid_message_content"
    try:
        _normalize_message_content(
            [{"type": "image_url", "image_url": {"url": "https://x", "detail": "ultra"}}]
        )
        raise AssertionError("expected invalid detail")
    except RequestError as exc:
        assert exc.code == "invalid_message_content"


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


def test_http_chat_accepts_image_url_parts() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "describe"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "https://example.com/cat.png",
                                    "detail": "auto",
                                },
                            },
                        ],
                    }
                ],
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_bad_image_url() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": ""}}],
                    }
                ],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_message_content"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_normalize_and_detect_image_parts()
    test_http_chat_accepts_image_url_parts()
    test_http_chat_rejects_bad_image_url()
    print("ok")
