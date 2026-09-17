"""CI gateway bootstrap contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

from contextual_orchestrator.credentials import get_credential
from contextual_orchestrator.model_discovery import DiscoveredModel, PROVIDER_MODEL_SOURCES
from contextual_orchestrator.server import build_server


def _bootstrap_module():
    path = Path(__file__).parents[1] / "scripts" / "ci" / "serve_seeded_gateway.py"
    spec = importlib.util.spec_from_file_location("serve_seeded_gateway", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    headers = {"connection": "close"}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    payload = None
    if body is not None:
        headers["content-type"] = "application/json"
        payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _assert_unauthorized(
    method: str,
    url: str,
    *,
    token: str | None,
    body: dict[str, object] | None = None,
) -> None:
    status, payload = _request_json(method, url, token=token, body=body)
    assert status == 401, payload
    assert payload["error"]["code"] == "unauthorized"


def test_seed_credentials_copies_present_provider_keys_into_kv(monkeypatch) -> None:
    module = _bootstrap_module()
    assert module.PROVIDER_KEY_ENV_NAMES == tuple(
        dict.fromkeys(source.credential_name for source in PROVIDER_MODEL_SOURCES)
    )
    for name in module.PROVIDER_KEY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "zen-secret")
    monkeypatch.setenv(module.SERVER_AUTH_ENV_NAME, "-loopback-token")

    assert module.seed_credentials_from_bootstrap_env() == [
        "OPENROUTER_API_KEY",
        "OPENCODE_ZEN_API_KEY",
        module.SERVER_AUTH_ENV_NAME,
    ]
    assert "OPENROUTER_API_KEY" not in module.os.environ
    assert "OPENCODE_ZEN_API_KEY" not in module.os.environ
    assert module.SERVER_AUTH_ENV_NAME not in module.os.environ
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "changed-after-bootstrap")
    assert get_credential("OPENCODE_ZEN_API_KEY") == "zen-secret"
    assert get_credential(module.SERVER_AUTH_ENV_NAME) == "-loopback-token"


def test_main_serves_authenticated_models_and_orchestrator_free_from_bootstrap(
    monkeypatch,
) -> None:
    """The Actions bootstrap path serves authenticated owner-owned free routing."""
    module = _bootstrap_module()
    provider_requests: list[dict[str, object]] = []
    discovered = DiscoveredModel(
        provider_name="openrouter",
        model_id="free-mock-model",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://provider.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        prompt_price_per_1k=0.0,
        completion_price_per_1k=0.0,
        is_free=True,
    )
    captured: dict[str, object] = {}

    def fake_serve(orchestrator, **kwargs):
        server = build_server(orchestrator, **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        captured["server"] = server
        captured["thread"] = thread

    monkeypatch.setattr("contextual_orchestrator.__main__.serve", fake_serve)
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([discovered], []),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.refresh_price_book",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_provider_models",
        lambda *_args, **_kwargs: ([discovered], []),
        raising=False,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.orchestrator.ModelClient._validate_provider",
        lambda self, agent: (0, ("127.0.0.1", 443)),
    )

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self._body = json.dumps(payload).encode("utf-8")

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    def fake_open_provider(self, request, destination=None, *, timeout=None):
        del self, destination, timeout
        provider_requests.append(
            {
                "url": request.full_url,
                "authorization": request.get_header("Authorization"),
                "body": json.loads(request.data.decode("utf-8")),
            }
        )
        return _FakeResponse(
            {
                "id": "chatcmpl-provider",
                "object": "chat.completion",
                "created": 0,
                "model": "free-mock-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "verify the owner boundary",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
            }
        )

    monkeypatch.setattr(
        "contextual_orchestrator.orchestrator.ModelClient._open_provider",
        fake_open_provider,
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv(module.SERVER_AUTH_ENV_NAME, "loopback-owner-token")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "serve_seeded_gateway",
            "--serve",
            "--agents",
            "examples/agents.mock.json",
            "--auto-discover-model-agents",
            "--auth-token-key",
            module.SERVER_AUTH_ENV_NAME,
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
    )

    module.main()

    server = captured["server"]
    thread = captured["thread"]
    try:
        assert get_credential("OPENROUTER_API_KEY") == "router-secret"
        assert get_credential(module.SERVER_AUTH_ENV_NAME) == "loopback-owner-token"
        assert "OPENROUTER_API_KEY" not in module.os.environ
        assert module.SERVER_AUTH_ENV_NAME not in module.os.environ
        port = server.server_address[1]
        models_url = f"http://127.0.0.1:{port}/v1/models"
        chat_url = f"http://127.0.0.1:{port}/v1/chat/completions"
        chat_request = {
            "model": "orchestrator/free",
            "messages": [{"role": "user", "content": "verify the owner boundary"}],
        }
        for token in (None, "wrong-owner-token"):
            _assert_unauthorized("GET", models_url, token=token)
            _assert_unauthorized("POST", chat_url, token=token, body=chat_request)
        models_status, models_body = _request_json(
            "GET",
            models_url,
            token="loopback-owner-token",
        )
        assert models_status == 200, models_body
        model_ids = [item["id"] for item in models_body["data"]]
        assert "contextual-orchestrator" in model_ids
        assert "orchestrator/free" in model_ids
        assert "free-mock-model" in model_ids
        models_blob = json.dumps(models_body)
        assert "mock://" not in models_blob
        assert discovered.chat_base_url not in models_blob
        assert "OPENROUTER_API_KEY" not in models_blob
        assert "router-secret" not in models_blob

        chat_status, chat_body = _request_json(
            "POST",
            chat_url,
            token="loopback-owner-token",
            body=chat_request,
        )
        assert chat_status == 200, chat_body
        assert chat_body["object"] == "chat.completion"
        assert chat_body["model"] == "orchestrator/free"
        content = chat_body["choices"][0]["message"]["content"]
        assert "verify the owner boundary" in content
        matching_requests = [
            record
            for record in provider_requests
            if record["url"] == "https://provider.example/v1/chat/completions"
            and record["authorization"] == "Bearer router-secret"
            and isinstance(record["body"], dict)
            and record["body"].get("model") == "free-mock-model"
            and record["body"].get("messages") == [
                {"role": "user", "content": "verify the owner boundary"}
            ]
        ]
        assert matching_requests, provider_requests
        request_body = matching_requests[0]["body"]
        assert request_body["messages"] == [
            {"role": "user", "content": "verify the owner boundary"}
        ]
        chat_blob = json.dumps(chat_body)
        assert "router-secret" not in chat_blob
        assert "OPENROUTER_API_KEY" not in chat_blob
        assert discovered.chat_base_url not in chat_blob
        provider_blob = json.dumps(provider_requests)
        assert "router-secret" in provider_blob
        assert "OPENROUTER_API_KEY" not in provider_blob
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_main_fails_closed_when_bootstrap_has_no_free_route(monkeypatch) -> None:
    """The Actions bootstrap path does not promote orchestrator/free to paid models."""
    module = _bootstrap_module()
    paid = DiscoveredModel(
        provider_name="openrouter",
        model_id="paid-mock-model",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="mock://paid-owner-gateway",
        auth_scheme="Bearer",
        capabilities=("chat",),
        prompt_price_per_1k=0.1,
        completion_price_per_1k=0.2,
        is_free=False,
    )
    captured: dict[str, object] = {}

    def fake_serve(orchestrator, **kwargs):
        server = build_server(orchestrator, **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        captured["server"] = server
        captured["thread"] = thread

    monkeypatch.setattr("contextual_orchestrator.__main__.serve", fake_serve)
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([paid], []),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.refresh_price_book",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv(module.SERVER_AUTH_ENV_NAME, "loopback-owner-token")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "serve_seeded_gateway",
            "--serve",
            "--agents",
            "examples/agents.mock.json",
            "--auto-discover-model-agents",
            "--auth-token-key",
            module.SERVER_AUTH_ENV_NAME,
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
    )

    module.main()

    server = captured["server"]
    thread = captured["thread"]
    try:
        port = server.server_address[1]
        models_status, models_body = _request_json(
            "GET",
            f"http://127.0.0.1:{port}/v1/models",
            token="loopback-owner-token",
        )
        assert models_status == 200, models_body
        model_ids = [item["id"] for item in models_body["data"]]
        assert "paid-mock-model" in model_ids
        assert "orchestrator/free" not in model_ids

        chat_status, chat_body = _request_json(
            "POST",
            f"http://127.0.0.1:{port}/v1/chat/completions",
            token="loopback-owner-token",
            body={
                "model": "orchestrator/free",
                "messages": [{"role": "user", "content": "stay fail closed"}],
            },
        )
        assert chat_status == 400, chat_body
        assert chat_body["error"]["code"] == "invalid_model"
        assert "zero-cost" in chat_body["error"]["message"]
        error_blob = json.dumps(chat_body)
        assert "paid-mock-model" not in error_blob
        assert "router-secret" not in error_blob
        assert "OPENROUTER_API_KEY" not in error_blob
        assert "mock://" not in error_blob
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
