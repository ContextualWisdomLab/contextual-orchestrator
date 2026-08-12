"""OpenAI-compatible GET /v1/models discovery for gateway consumers."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.api_contract import OPENAPI_SPEC  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "secret_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing")),
            ModelAgent("coding_agent", "mock-coder", tags=("coding",)),
            ModelAgent("duplicate_agent", "mock-generalist", tags=("reasoning",)),
            ModelAgent("disabled_agent", "mock-disabled", tags=("writing",), disabled=True),
        ]
    )


def _get_json(url: str, token: str | None = None) -> tuple[int, dict[str, object]]:
    headers = {"connection": "close"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_list_openai_models_requires_inference_bearer() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _get_json(f"http://127.0.0.1:{port}/v1/models")
        assert status == 401
        assert body["error"]["code"] == "unauthorized"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_list_openai_models_returns_gateway_default_and_unique_agent_models() -> None:
    """Buyer path: OpenAI clients can discover selectable model ids from the pool."""
    orchestrator = build()
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _get_json(f"http://127.0.0.1:{port}/v1/models", token=_TEST_AUTH_TOKEN)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert body["object"] == "list"
    ids = [item["id"] for item in body["data"]]  # type: ignore[index]
    assert ids[0] == "contextual-orchestrator"
    assert "mock-generalist" in ids
    assert "mock-coder" in ids
    assert ids.count("mock-generalist") == 1
    assert "mock-disabled" not in ids
    for item in body["data"]:  # type: ignore[union-attr]
        assert item["object"] == "model"
        assert "created" in item
        assert "owned_by" in item


def test_get_openai_model_by_id_and_missing() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        ok_status, ok_body = _get_json(
            f"http://127.0.0.1:{port}/v1/models/mock-coder",
            token=_TEST_AUTH_TOKEN,
        )
        missing_status, missing_body = _get_json(
            f"http://127.0.0.1:{port}/v1/models/not-a-model",
            token=_TEST_AUTH_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert ok_status == 200
    assert ok_body["id"] == "mock-coder"
    assert ok_body["object"] == "model"
    assert missing_status == 404
    assert missing_body["error"]["code"] == "model_not_found"


def test_openapi_contract_includes_v1_models() -> None:
    assert "/v1/models" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/v1/models"]["get"]["operationId"] == "list_openai_models"
    assert "/v1/models/{model_id}" in OPENAPI_SPEC["paths"]


def test_list_openai_models_domain_helper_is_secret_free() -> None:
    """Domain listing never echoes credential names or base URLs into model objects."""
    payload = build().list_openai_models()
    raw = json.dumps(payload)
    assert "OPENAI_API_KEY" not in raw
    assert "mock://" not in raw
    assert "credential" not in raw


def test_route_prefers_agent_matching_requested_model_id() -> None:
    """Selecting a /v1/models id steers the worker route to that agent model."""
    orchestrator = build()
    result = orchestrator.route_once(
        [{"role": "user", "content": "hello"}],
        preferred_model="mock-coder",
    )
    assert result["trace"][0]["agent_id"] == "coding_agent"
    # Gateway default and unknown ids do not force a match.
    defaulted = orchestrator.route_once(
        [{"role": "user", "content": "hello"}],
        preferred_model="contextual-orchestrator",
    )
    assert defaulted["trace"][0]["agent_id"] in {"general_agent", "coding_agent", "duplicate_agent"}


if __name__ == "__main__":
    test_list_openai_models_requires_inference_bearer()
    test_list_openai_models_returns_gateway_default_and_unique_agent_models()
    test_get_openai_model_by_id_and_missing()
    test_openapi_contract_includes_v1_models()
    test_list_openai_models_domain_helper_is_secret_free()
    test_route_prefers_agent_matching_requested_model_id()
    print("ok")
