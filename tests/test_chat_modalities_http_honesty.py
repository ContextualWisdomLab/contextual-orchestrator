"""Chat Completions modalities honesty over HTTP.

Text-only unless a caller opts into OpenAI's audio-output shape
(``modalities: ["text", "audio"]`` + ``audio: {voice, format}``), which
routes to single-agent passthrough exactly like ``/v1/audio/generations``
(see ``test_openai_sdk_compat.py`` for a real SDK round trip through that
path)."""

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

_TEST_AUTH_TOKEN = "chat_modalities_http_honesty_token"  # noqa: S105


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


def test_http_chat_accepts_modalities_text_only() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "text only"}],
                "modalities": ["text"],
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_modalities_audio() -> None:
    """Buyers must not believe audio output was produced by a text-only gateway."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "speak"}],
                "modalities": ["audio"],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_modalities" in blob
        assert "text" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_modalities_text_and_audio_without_audio_object() -> None:
    """Opting into audio output still requires audio.voice and audio.format."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "both"}],
                "modalities": ["text", "audio"],
            },
        )
        assert status == 400, body
        assert "invalid_audio" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_audio_output_modalities_reach_the_audio_capability_route() -> None:
    """A well-shaped audio-output request is not rejected outright.

    modalities=["text","audio"] + audio{voice,format} fails closed on
    capability availability (no audio-tagged agent here), not on
    modalities/audio shape.
    """
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "speak"}],
                "modalities": ["text", "audio"],
                "audio": {"voice": "alloy", "format": "wav"},
            },
        )
        assert status == 503, body
        assert "capability_unavailable" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_empty_modalities_as_omit() -> None:
    """Empty modalities [] is an omit-equivalent SDK optional default."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "empty mods"}],
                "modalities": [],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_modalities_non_array() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "string mods"}],
                "modalities": "text",
            },
        )
        assert status == 400, body
        assert "invalid_modalities" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_modalities_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "default modalities"}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_modalities_text_only()
    test_http_chat_rejects_modalities_audio()
    test_http_chat_rejects_modalities_text_and_audio_without_audio_object()
    test_http_chat_audio_output_modalities_reach_the_audio_capability_route()
    test_http_chat_accepts_empty_modalities_as_omit()
    test_http_chat_rejects_modalities_non_array()
    test_http_chat_accepts_modalities_omitted()
    print("ok")
