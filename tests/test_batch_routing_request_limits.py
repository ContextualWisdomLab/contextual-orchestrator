"""Batch routing job request count and model shape validation."""

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
    MAX_BATCH_ROUTING_REQUESTS,
    RequestError,
    SecurityConfig,
    _validate_batch_requests,
    build_server,
)

_TEST_AUTH_TOKEN = "batch_lim_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _item(model: str = "mock-generalist") -> dict:
    return {
        "messages": [{"role": "user", "content": "hi"}],
        "model": model,
        "mode": "route",
    }


def test_validate_batch_request_limits_and_models() -> None:
    ok = _validate_batch_requests({"requests": [_item()]}, expose_trace=False)
    assert len(ok) == 1
    assert ok[0].model == "mock-generalist"
    try:
        _validate_batch_requests(
            {"requests": [_item() for _ in range(MAX_BATCH_ROUTING_REQUESTS + 1)]},
            expose_trace=False,
        )
        raise AssertionError("over limit")
    except RequestError as exc:
        assert exc.code == "invalid_request"
        assert exc.detail.get("max_batch_routing_requests") == MAX_BATCH_ROUTING_REQUESTS
    try:
        _validate_batch_requests({"requests": [_item("")], "model": "top"}, expose_trace=False)
        raise AssertionError("blank item model")
    except RequestError as exc:
        assert exc.code == "invalid_model"
    try:
        _validate_batch_requests({"requests": [_item()], "model": "  "}, expose_trace=False)
        raise AssertionError("blank top model")
    except RequestError as exc:
        assert exc.code == "invalid_model"


def test_http_rejects_oversized_batch() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        payload = {
            "requests": [
                {"messages": [{"role": "user", "content": "x"}], "mode": "route"}
                for _ in range(MAX_BATCH_ROUTING_REQUESTS + 1)
            ]
        }
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
            urllib.request.urlopen(request, timeout=10)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"]["code"] == "invalid_request"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_batch_request_limits_and_models()
    test_http_rejects_oversized_batch()
    print("ok")
