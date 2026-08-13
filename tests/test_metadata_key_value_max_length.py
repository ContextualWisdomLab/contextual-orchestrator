"""OpenAI metadata keys/values ≤64 chars and ≤16 pairs."""

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
    _MAX_METADATA_PAIRS,
    _MAX_METADATA_STRING_CHARS,
    _validate_openai_metadata_map,
    build_server,
)

_TEST_AUTH_TOKEN = "meta_kv_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_openai_metadata_map() -> None:
    assert _MAX_METADATA_STRING_CHARS == 64
    assert _MAX_METADATA_PAIRS == 16
    assert _validate_openai_metadata_map({}) is None
    body = {"metadata": {"team": "platform", "env": "prod"}}
    assert _validate_openai_metadata_map(body) == {"team": "platform", "env": "prod"}
    try:
        _validate_openai_metadata_map({"metadata": {("k" * 65): "v"}})
        raise AssertionError("expected invalid_metadata key length")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"
    try:
        _validate_openai_metadata_map({"metadata": {"k": "v" * 65}})
        raise AssertionError("expected invalid_metadata value length")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"
    try:
        _validate_openai_metadata_map(
            {"metadata": {f"k{i}": "v" for i in range(17)}}
        )
        raise AssertionError("expected invalid_metadata pair count")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"


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


def test_http_rejects_oversize_metadata_value() -> None:
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
                "metadata": {"trace": "x" * 65},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_metadata"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_metadata_at_cap() -> None:
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
                "metadata": {"k" * 64: "v" * 64},
            },
        )
        assert status == 200, body
        assert body["choices"][0]["message"]["content"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_openai_metadata_map()
    test_http_rejects_oversize_metadata_value()
    test_http_accepts_metadata_at_cap()
    print("ok")
