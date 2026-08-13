"""OpenAI input_audio content parts on chat messages force audio passthrough."""

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
    _message_has_input_audio_content,
    _normalize_message_content,
    build_server,
)

_TEST_AUTH_TOKEN = "input_audio_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_normalize_and_detect_input_audio() -> None:
    assert _normalize_message_content("hi") == "hi"
    assert (
        _normalize_message_content(
            [
                {"type": "text", "text": "transcribe"},
                {
                    "type": "input_audio",
                    "input_audio": {"data": "AAAA", "format": "wav"},
                },
            ]
        )
        == "transcribe"
    )
    assert (
        _normalize_message_content(
            [{"type": "input_audio", "input_audio": {"data": "AAAA", "format": "mp3"}}]
        )
        == "[audio]"
    )
    assert _message_has_input_audio_content(
        [
            {
                "role": "user",
                "content": [{"type": "input_audio", "input_audio": {"data": "AAAA"}}],
            }
        ]
    )
    try:
        _normalize_message_content(
            [{"type": "input_audio", "input_audio": {"data": ""}}]
        )
        raise AssertionError("expected empty data reject")
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


def test_http_chat_accepts_input_audio_parts() -> None:
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
                            {"type": "text", "text": "what did I say?"},
                            {
                                "type": "input_audio",
                                "input_audio": {"data": "UklGRg==", "format": "wav"},
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


def test_http_chat_rejects_empty_audio_data() -> None:
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
                            {"type": "input_audio", "input_audio": {"data": ""}},
                        ],
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
    test_normalize_and_detect_input_audio()
    test_http_chat_accepts_input_audio_parts()
    test_http_chat_rejects_empty_audio_data()
    print("ok")
