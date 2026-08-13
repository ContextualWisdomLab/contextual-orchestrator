"""Batch routing job metadata map validation."""

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
    _validate_batch_metadata,
    build_server,
)

_TEST_AUTH_TOKEN = "batch_meta_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_batch_metadata() -> None:
    assert _validate_batch_metadata({}) is None
    assert _validate_batch_metadata({"metadata": {"team": "ops"}}) == {"team": "ops"}
    try:
        _validate_batch_metadata({"metadata": {"n": 1}})
        raise AssertionError("int")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/batch_routing_jobs",
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


def test_http_accepts_metadata() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "requests": [
                    {
                        "messages": [{"role": "user", "content": "hi"}],
                        "mode": "route",
                    }
                ],
                "metadata": {"source": "buyer-batch"},
            },
        )
        assert status in {200, 201, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_bad_metadata() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "requests": [
                    {
                        "messages": [{"role": "user", "content": "hi"}],
                        "mode": "route",
                    }
                ],
                "metadata": {"count": 3},
            },
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_metadata"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_batch_metadata()
    test_http_accepts_metadata()
    test_http_rejects_bad_metadata()
    print("ok")
