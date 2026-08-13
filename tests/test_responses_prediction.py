"""OpenAI Responses prediction content-shape validation."""

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
    _validate_responses_prediction,
    build_server,
)

_TEST_AUTH_TOKEN = "resp_pred_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_prediction() -> None:
    assert _validate_responses_prediction({}) is None
    good = {"type": "content", "content": "draft answer"}
    assert _validate_responses_prediction({"prediction": good}) == good
    parts = {
        "type": "content",
        "content": [{"type": "text", "text": "draft"}],
    }
    assert _validate_responses_prediction({"prediction": parts}) == parts
    for bad in (
        "x",
        {"type": "other", "content": "x"},
        {"type": "content", "content": ""},
        {"type": "content", "content": []},
        {"type": "content", "content": [{"type": "image"}]},
        {"type": "content", "content": [{"type": "text", "text": ""}]},
    ):
        try:
            _validate_responses_prediction({"prediction": bad})
            raise AssertionError(f"expected reject for {bad!r}")
        except RequestError as exc:
            assert exc.code == "invalid_prediction"


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


def test_http_accepts_prediction() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-generalist",
                "input": "hi",
                "prediction": {"type": "content", "content": "expected"},
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_bad_prediction() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-generalist",
                "input": "hi",
                "prediction": {"type": "content", "content": ""},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_prediction"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_prediction()
    test_http_accepts_prediction()
    test_http_rejects_bad_prediction()
    print("ok")
