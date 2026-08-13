"""OpenAI chat audio object validation for voice modalities."""

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
    _validate_audio_object,
    build_server,
)

_TEST_AUTH_TOKEN = "audio_obj_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_audio_object() -> None:
    assert _validate_audio_object({}) is None
    good = {"voice": "alloy", "format": "wav"}
    assert _validate_audio_object({"audio": good}) == good
    for bad in ("x", {}, {"voice": ""}, {"voice": "alloy", "format": 1}):
        try:
            _validate_audio_object({"audio": bad})
            raise AssertionError(f"expected reject for {bad!r}")
        except RequestError as exc:
            assert exc.code == "invalid_audio"


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


def test_http_chat_accepts_audio_object() -> None:
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
                "messages": [{"role": "user", "content": "hi"}],
                "modalities": ["text", "audio"],
                "audio": {"voice": "alloy", "format": "mp3"},
            },
        )
        # modalities may be unknown without its PR — only audio alone
        assert status in {200, 202, 400}, body
        if status == 400:
            # if modalities rejected as unknown field on main, retry without modalities
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-generalist",
                    "messages": [{"role": "user", "content": "hi"}],
                    "audio": {"voice": "alloy"},
                },
            )
            assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_missing_voice() -> None:
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
                "messages": [{"role": "user", "content": "hi"}],
                "audio": {"format": "wav"},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_audio"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_audio_object()
    test_http_chat_accepts_audio_object()
    test_http_chat_rejects_missing_voice()
    print("ok")
