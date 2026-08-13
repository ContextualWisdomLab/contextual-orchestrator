"""OpenAI GET /v1/models discovery honesty over real HTTP."""

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

_TEST_AUTH_TOKEN = "openai_models_listing_http_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing")),
            ModelAgent("coding_agent", "mock-coder", tags=("coding",)),
            ModelAgent("duplicate_agent", "mock-generalist", tags=("reasoning",)),
            ModelAgent("disabled_agent", "mock-disabled", tags=("writing",), disabled=True),
        ]
    )


def _get(port: int, path: str, token: str | None = None) -> tuple[int, dict]:
    headers = {"connection": "close"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server(orchestrator: TaskOrchestrator | None = None):
    orch = orchestrator or build()
    server = build_server(orch, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_models_list_requires_bearer() -> None:
    server, thread, port = _server()
    try:
        status, body = _get(port, "/v1/models")
        assert status == 401, body
        assert "unauthorized" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_models_list_unique_enabled_pool_models() -> None:
    server, thread, port = _server()
    try:
        status, body = _get(port, "/v1/models", token=_TEST_AUTH_TOKEN)
        assert status == 200, body
        assert body.get("object") == "list"
        ids = [item["id"] for item in body["data"]]
        assert ids[0] == "contextual-orchestrator"
        assert "mock-generalist" in ids
        assert "mock-coder" in ids
        assert ids.count("mock-generalist") == 1
        assert "mock-disabled" not in ids
        for item in body["data"]:
            assert item["object"] == "model"
            assert "created" in item
            assert "owned_by" in item
        # Secret-free: no base URLs or credential hints.
        blob = json.dumps(body)
        assert "mock://" not in blob
        assert "OPENAI_API_KEY" not in blob
        assert "credential" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_models_get_by_id() -> None:
    server, thread, port = _server()
    try:
        status, body = _get(port, "/v1/models/mock-coder", token=_TEST_AUTH_TOKEN)
        assert status == 200, body
        assert body.get("id") == "mock-coder"
        assert body.get("object") == "model"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_models_get_missing_is_404() -> None:
    server, thread, port = _server()
    try:
        status, body = _get(port, "/v1/models/not-a-model", token=_TEST_AUTH_TOKEN)
        assert status == 404, body
        assert "model_not_found" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_models_domain_helper_matches_http() -> None:
    orch = build()
    domain = orch.list_openai_models()
    server, thread, port = _server(orch)
    try:
        status, body = _get(port, "/v1/models", token=_TEST_AUTH_TOKEN)
        assert status == 200, body
        assert body == domain
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_models_list_requires_bearer()
    test_http_models_list_unique_enabled_pool_models()
    test_http_models_get_by_id()
    test_http_models_get_missing_is_404()
    test_http_models_domain_helper_matches_http()
    print("ok")
