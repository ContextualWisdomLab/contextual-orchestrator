"""OpenAI content-part arrays on chat message content (SDK drop-in)."""

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
    _normalize_message_content,
    _validate_messages,
    build_server,
)

_TEST_AUTH_TOKEN = "content_parts_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_normalize_string_and_text_parts() -> None:
    assert _normalize_message_content("hello") == "hello"
    assert (
        _normalize_message_content(
            [{"type": "text", "text": "line one"}, {"type": "text", "text": "line two"}]
        )
        == "line one\nline two"
    )
    assert _normalize_message_content(["plain", "parts"]) == "plain\nparts"


def test_normalize_rejects_image_and_empty() -> None:
    try:
        _normalize_message_content(
            [{"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}]
        )
        raise AssertionError("expected invalid_message_content")
    except RequestError as exc:
        assert exc.code == "invalid_message_content"
        assert exc.detail.get("part_type") == "image_url"
    try:
        _normalize_message_content([])
        raise AssertionError("expected invalid_message")
    except RequestError as exc:
        assert exc.code == "invalid_message"
    try:
        _normalize_message_content([{"type": "text", "text": ""}])
        raise AssertionError("expected invalid_message for empty text parts")
    except RequestError as exc:
        assert exc.code == "invalid_message"


def test_validate_messages_accepts_content_parts() -> None:
    validated = _validate_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Summarize"},
                    {"type": "text", "text": "the architecture."},
                ],
            }
        ]
    )
    assert validated == [
        {"role": "user", "content": "Summarize\nthe architecture."}
    ]


def test_http_chat_accepts_openai_content_parts() -> None:
    """Buyer path: modern SDKs send content as part arrays even for text-only."""
    orchestrator = build()
    server = build_server(
        orchestrator,
        host="127.0.0.1",
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        payload = {
            "model": "contextual-orchestrator",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Write a short hello."},
                    ],
                }
            ],
            "mode": "route",
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert isinstance(body["choices"][0]["message"]["content"], str)
        assert body["choices"][0]["message"]["content"]
    finally:
        server.shutdown()


def test_http_rejects_image_content_parts() -> None:
    orchestrator = build()
    server = build_server(
        orchestrator,
        host="127.0.0.1",
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.com/x.png"},
                        }
                    ],
                }
            ],
            "mode": "route",
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)  # noqa: S310
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            body = json.loads(exc.read().decode("utf-8"))
            code = body.get("error", {}).get("code") or body.get("error_code")
            assert code == "invalid_message_content"
    finally:
        server.shutdown()


if __name__ == "__main__":
    test_normalize_string_and_text_parts()
    test_normalize_rejects_image_and_empty()
    test_validate_messages_accepts_content_parts()
    test_http_chat_accepts_openai_content_parts()
    test_http_rejects_image_content_parts()
    print("ok")
