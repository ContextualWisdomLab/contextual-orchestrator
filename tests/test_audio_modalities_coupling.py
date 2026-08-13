"""audio object and modalities must be paired for OpenAI voice output."""

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
    _validate_audio_modalities_coupling,
    build_server,
)

_TEST_AUTH_TOKEN = "audio_mod_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_audio_modalities_coupling() -> None:
    _validate_audio_modalities_coupling({})
    _validate_audio_modalities_coupling({"modalities": ["text"]})
    _validate_audio_modalities_coupling(
        {"modalities": ["text", "audio"], "audio": {"voice": "alloy"}}
    )
    try:
        _validate_audio_modalities_coupling({"audio": {"voice": "alloy"}})
        raise AssertionError("expected invalid_audio")
    except RequestError as exc:
        assert exc.code == "invalid_audio"
    try:
        _validate_audio_modalities_coupling({"modalities": ["text", "audio"]})
        raise AssertionError("expected invalid_modalities")
    except RequestError as exc:
        assert exc.code == "invalid_modalities"
    try:
        _validate_audio_modalities_coupling(
            {"modalities": ["audio"], "audio": "bad"}
        )
        raise AssertionError("expected invalid_audio object")
    except RequestError as exc:
        assert exc.code == "invalid_audio"


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


def test_http_rejects_audio_without_modalities() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "audio": {"voice": "alloy", "format": "mp3"},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_audio"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_paired_audio_modalities() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "modalities": ["text", "audio"],
                "audio": {"voice": "alloy", "format": "wav"},
            },
        )
        assert status == 200, body
        assert body["choices"][0]["message"]["content"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_audio_modalities_coupling()
    test_http_rejects_audio_without_modalities()
    test_http_accepts_paired_audio_modalities()
    print("ok")
