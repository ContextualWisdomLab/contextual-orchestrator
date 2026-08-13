"""GET/DELETE Responses storage paths return 501 not_implemented (create-proxy only)."""

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

_TEST_AUTH_TOKEN = "resp_store_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _request(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
        "connection": "close",
    }
    if payload is not None:
        headers["content-type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_get_responses_list_and_retrieve_return_501() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        for path in ("/v1/responses", "/v1/responses/resp_abc"):
            status, body = _request("GET", f"http://127.0.0.1:{port}{path}")
            assert status == 501, (path, body)
            assert body["error"]["code"] == "not_implemented"
            assert "POST /v1/responses" in body["error"]["message"]
        # Unknown path still 404 (not 501)
        status, body = _request("GET", f"http://127.0.0.1:{port}/v1/totally-unknown")
        assert status == 404
        assert body["error"]["code"] == "route_not_found"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_delete_response_returns_501() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _request("DELETE", f"http://127.0.0.1:{port}/v1/responses/resp_abc")
        assert status == 501, body
        assert body["error"]["code"] == "not_implemented"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_post_responses_still_works() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _request(
            "POST",
            f"http://127.0.0.1:{port}/v1/responses",
            {"model": "mock-generalist", "input": "hi"},
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_get_responses_list_and_retrieve_return_501()
    test_delete_response_returns_501()
    test_post_responses_still_works()
    print("ok")
