"""Reject empty text content parts; accept multi-part text substrate."""

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

_TEST_AUTH_TOKEN = "empty_text_parts_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_normalize_accepts_nonempty_text_parts() -> None:
    assert _normalize_message_content("hello") == "hello"
    assert (
        _normalize_message_content(
            [{"type": "text", "text": "line one"}, {"type": "text", "text": "line two"}]
        )
        == "line one\nline two"
    )


def test_normalize_rejects_empty_text_parts() -> None:
    try:
        _normalize_message_content([{"type": "text", "text": ""}])
        raise AssertionError("expected invalid_message_content empty")
    except RequestError as exc:
        assert exc.code == "invalid_message_content"
        assert exc.detail.get("part_index") == 0
    try:
        _normalize_message_content([{"type": "text", "text": "  "}])
        raise AssertionError("expected invalid_message_content whitespace")
    except RequestError as exc:
        assert exc.code == "invalid_message_content"
    try:
        _normalize_message_content(
            [
                {"type": "text", "text": "ok"},
                {"type": "text", "text": ""},
            ]
        )
        raise AssertionError("expected invalid_message_content mixed empty")
    except RequestError as exc:
        assert exc.code == "invalid_message_content"
        assert exc.detail.get("part_index") == 1
    try:
        _normalize_message_content([""])
        raise AssertionError("expected invalid_message_content bare empty string part")
    except RequestError as exc:
        assert exc.code == "invalid_message_content"


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


def test_http_rejects_empty_text_content_parts() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": ""}],
                    }
                ],
                "mode": "route",
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_message_content"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_nonempty_text_content_parts() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "Write a short hello."}],
                    }
                ],
                "mode": "route",
            },
        )
        assert status == 200, body
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["content"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_normalize_accepts_nonempty_text_parts()
    test_normalize_rejects_empty_text_parts()
    test_validate_messages_accepts_content_parts()
    test_http_rejects_empty_text_content_parts()
    test_http_accepts_nonempty_text_content_parts()
    print("ok")
