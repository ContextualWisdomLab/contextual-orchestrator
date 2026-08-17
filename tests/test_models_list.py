"""OpenAI-compatible GET /v1/models and provider catalog admin surfaces."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import InMemoryCredentialBackend, register_credential, set_backend  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def _start():
    set_backend(InMemoryCredentialBackend())
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )
    orchestrator.catalog_fetcher = lambda endpoint, key: {
        "data": [
            {"id": "gpt-4.1", "owned_by": "openai"},
            {"id": "o4-mini", "owned_by": "openai"},
        ]
    }
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, orchestrator, server.server_address[1]


def _json(port: int, path: str, token: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_models_list_requires_inference_bearer() -> None:
    server, thread, _orchestrator, port = _start()
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models")
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected 401")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        status, body = _json(port, "/v1/models", "inference_secret")
        assert status == 200
        assert body["object"] == "list"
        assert body["data"][0]["id"] == "contextual-orchestrator"
        assert any(row["id"] == "mock-generalist" for row in body["data"])
    finally:
        server.shutdown()
        thread.join(timeout=5)
        set_backend(None)


def test_refresh_replaces_pool_from_registered_key() -> None:
    server, thread, orchestrator, port = _start()
    try:
        register_credential("OPENAI_API_KEY", "sk-test")
        status, body = _json(port, "/api/v1/provider_catalogs/refresh", "admin_secret", method="POST", body={})
        assert status == 200
        assert body["used_floor"] is False
        assert body["source"] == "live"
        assert {row["model_id"] for row in body["models"]} == {"gpt-4.1", "o4-mini"}
        status, listed = _json(port, "/v1/models", "inference_secret")
        assert status == 200
        ids = [row["id"] for row in listed["data"]]
        assert "gpt-4.1" in ids
        assert "o4-mini" in ids
        assert "mock-generalist" not in ids
        status, snapshot = _json(port, "/api/v1/provider_catalogs", "admin_secret")
        assert status == 200
        assert snapshot["model_count"] == 2
        assert orchestrator.discovery_snapshot["source"] == "live"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        set_backend(None)


def test_bodyless_refresh_keeps_seed_when_unregistered() -> None:
    server, thread, orchestrator, port = _start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1/provider_catalogs/refresh",
            headers={"authorization": "Bearer admin_secret"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
        assert status == 200
        assert body["source"] == "seed"
        assert body["used_floor"] is False
        assert orchestrator.agents[0].id == "general_agent"
        served_status, listed = _json(port, "/v1/models", "inference_secret")
        assert served_status == 200
        assert any(row["id"] == "mock-generalist" for row in listed["data"])
    finally:
        server.shutdown()
        thread.join(timeout=5)
        set_backend(None)


if __name__ == "__main__":  # pragma: no cover
    test_models_list_requires_inference_bearer()
    test_refresh_replaces_pool_from_registered_key()
    test_bodyless_refresh_keeps_seed_when_unregistered()
    print("ok")
