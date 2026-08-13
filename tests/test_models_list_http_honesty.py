"""GET /v1/models pool listing honesty over real HTTP outcomes."""

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

_TEST_AUTH_TOKEN = "models_list_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent(
                "general_agent",
                "mock-planner",
                tags=("reasoning", "writing", "embedding"),
                provider_name="mock_provider",
            ),
            ModelAgent(
                "coder_agent",
                "mock-builder",
                tags=("coding",),
                provider_name="mock_provider",
            ),
            ModelAgent(
                "retired_agent",
                "mock-retired",
                tags=("writing",),
                disabled=True,
                provider_name="offline",
            ),
        ]
    )


def _get(port: int, path: str, *, token: str | None = _TEST_AUTH_TOKEN) -> tuple[int, dict | str]:
    headers = {"connection": "close"}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_models_list_requires_inference_auth() -> None:
    server, thread, port = _server()
    try:
        status, body = _get(port, "/v1/models", token=None)
        assert status in {401, 403}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_models_list_returns_enabled_pool_only() -> None:
    server, thread, port = _server()
    try:
        status, body = _get(port, "/v1/models")
        assert status == 200, body
        assert isinstance(body, dict)
        assert body.get("object") == "list"
        data = body.get("data")
        assert isinstance(data, list)
        ids = [item["id"] for item in data]
        assert ids == ["mock-planner", "mock-builder"]
        assert "mock-retired" not in ids
        for item in data:
            assert item.get("object") == "model"
            assert isinstance(item.get("created"), int)
            assert item.get("owned_by") == "mock_provider"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_models_get_accepts_pool_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _get(port, "/v1/models/mock-planner")
        assert status == 200, body
        assert isinstance(body, dict)
        assert body.get("id") == "mock-planner"
        assert body.get("object") == "model"
        assert body.get("owned_by") == "mock_provider"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_models_get_rejects_model_outside_agent_pool() -> None:
    server, thread, port = _server()
    try:
        status, body = _get(port, "/v1/models/text-embedding-3-not-deployed")
        assert status == 404, body
        blob = json.dumps(body)
        assert "model_not_found" in blob
        assert "text-embedding-3-not-deployed" in blob
        assert "agent pool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_models_get_rejects_disabled_pool_model() -> None:
    """Disabled agents must not appear as retrievable OpenAI models."""
    server, thread, port = _server()
    try:
        status, body = _get(port, "/v1/models/mock-retired")
        assert status == 404, body
        assert "model_not_found" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_models_list_ids_usable_on_chat_completions() -> None:
    """Listed model ids must be accepted by chat so discovery stays honest."""
    server, thread, port = _server()
    try:
        status, body = _get(port, "/v1/models")
        assert status == 200, body
        assert isinstance(body, dict)
        model_id = body["data"][0]["id"]
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": model_id,
                    "messages": [{"role": "user", "content": "list models honesty"}],
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            chat_status = response.status
            chat_body = json.loads(response.read().decode("utf-8"))
        assert chat_status == 200, chat_body
        assert chat_body.get("model") == model_id or "choices" in chat_body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_models_list_requires_inference_auth()
    test_http_models_list_returns_enabled_pool_only()
    test_http_models_get_accepts_pool_model()
    test_http_models_get_rejects_model_outside_agent_pool()
    test_http_models_get_rejects_disabled_pool_model()
    test_http_models_list_ids_usable_on_chat_completions()
    print("ok")
