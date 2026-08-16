"""Live GET /v1/models is the primary catalog path (mock HTTP, no real keys).

After each org secret is in the KV, the gateway calls that host's OpenAI-compatible
list endpoint with ``get_credential`` — never ``os.getenv`` at request time.
Discovered chat models become the live pool. The static seed is only a fallback
when the list call 401/403/404/429/5xxs, is empty, or is malformed
(docs/doctoring/provider-catalog.md). GitHub Models stay out of catalog.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.provider_catalog import (  # noqa: E402
    compose_provider_catalog,
    seed_provider_catalog,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_backend():
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


class _ModelsProvider:
    """Loopback OpenAI-shaped GET /models (and optional Authorization capture)."""

    def __init__(self, status: int, body: object) -> None:
        self.status = status
        self.body = body
        self.authorization_headers: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                outer.authorization_headers.append(self.headers.get("authorization") or "")
                raw = (
                    outer.body
                    if isinstance(outer.body, bytes)
                    else json.dumps(outer.body).encode("utf-8")
                )
                self.send_response(outer.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_ModelsProvider":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"


def _nim_seed(base_url: str, model: str = "nvidia/seed-only-nemotron") -> ModelAgent:
    return ModelAgent(
        "nim_seed_only_agent",
        model,
        base_url,
        credential_key="NVIDIA_NIM_API_KEY",
        provider_name="nvidia_nim",
        tags=("reasoning", "coding"),
    )


def _openai_seed(base_url: str, model: str = "gpt-5.5") -> ModelAgent:
    return ModelAgent(
        "openai_seed_only_agent",
        model,
        base_url,
        credential_key="OPENAI_API_KEY",
        provider_name="openai",
        tags=("reasoning", "writing"),
    )


def test_registered_nim_key_discovers_chat_models_into_the_pool() -> None:
    register_credential("NVIDIA_NIM_API_KEY", "nvapi-fake")
    listing = {
        "data": [
            {"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5"},
            {"id": "nvidia/discovered-chat-model"},
            {"id": "nvidia/nv-embedqa-e5-v5"},
        ]
    }
    with _ModelsProvider(200, listing) as nim:
        ready, _skipped = compose_provider_catalog(
            [_nim_seed(nim.base_url)],
            discover=True,
            allow_insecure_discovery=True,
        )
    models = {agent.model for agent in ready}
    assert "nvidia/llama-3.3-nemotron-super-49b-v1.5" in models
    assert "nvidia/discovered-chat-model" in models
    assert "nvidia/nv-embedqa-e5-v5" not in models
    assert "nvidia/seed-only-nemotron" not in models
    assert all(agent.credential_name == "NVIDIA_NIM_API_KEY" for agent in ready)
    assert any("coding" in agent.tags or "reasoning" in agent.tags for agent in ready)
    assert nim.authorization_headers
    assert all(header == "Bearer nvapi-fake" for header in nim.authorization_headers)


def test_missing_key_skips_that_provider_others_still_discover() -> None:
    register_credential("OPENAI_API_KEY", "sk-only")
    listing = {"data": [{"id": "gpt-5.5-mini"}, {"id": "o4-mini"}]}
    with _ModelsProvider(200, listing) as openai:
        ready, skipped = compose_provider_catalog(
            [_nim_seed("https://integrate.api.nvidia.com/v1"), _openai_seed(openai.base_url)],
            discover=True,
            allow_insecure_discovery=True,
        )
    models = {agent.model for agent in ready}
    creds = {agent.credential_name for agent in ready}
    assert "gpt-5.5-mini" in models
    assert "o4-mini" in models
    assert "NVIDIA_NIM_API_KEY" not in creds
    assert any(row["reason"] == "credential_missing" for row in skipped)
    assert all(agent.credential_name == "OPENAI_API_KEY" for agent in ready)


def test_provider_models_429_keeps_static_seed_and_does_not_crash() -> None:
    register_credential("NVIDIA_NIM_API_KEY", "nvapi-rate-limited")
    with _ModelsProvider(429, {"error": "rate limited"}) as nim:
        ready, _skipped = compose_provider_catalog(
            [_nim_seed(nim.base_url)],
            discover=True,
            allow_insecure_discovery=True,
        )
    assert [agent.model for agent in ready] == ["nvidia/seed-only-nemotron"]
    assert [agent.id for agent in ready] == ["nim_seed_only_agent"]


def test_provider_models_5xx_keeps_static_seed() -> None:
    register_credential("NVIDIA_NIM_API_KEY", "nvapi-down")
    with _ModelsProvider(503, {"error": "unavailable"}) as nim:
        ready, _skipped = compose_provider_catalog(
            [_nim_seed(nim.base_url)],
            discover=True,
            allow_insecure_discovery=True,
        )
    assert [agent.model for agent in ready] == ["nvidia/seed-only-nemotron"]


def test_malformed_catalog_json_skips_that_listing_and_serves_the_rest() -> None:
    register_credential("NVIDIA_NIM_API_KEY", "nvapi-ok")
    register_credential("OPENAI_API_KEY", "sk-junk")
    nim_listing = {"data": [{"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5"}]}
    with _ModelsProvider(200, nim_listing) as nim, _ModelsProvider(200, b"{") as openai:
        ready, _skipped = compose_provider_catalog(
            [_nim_seed(nim.base_url), _openai_seed(openai.base_url)],
            discover=True,
            allow_insecure_discovery=True,
        )
    models = {agent.model for agent in ready}
    assert "nvidia/llama-3.3-nemotron-super-49b-v1.5" in models
    assert "nvidia/seed-only-nemotron" not in models
    assert "gpt-5.5" in models
    assert all("should-not" not in agent.model for agent in ready)


def test_discovered_catalog_never_includes_github_models() -> None:
    register_credential("OPENAI_API_KEY", "sk-ok")
    listing = {
        "data": [
            {"id": "gpt-5.5"},
            {"id": "gpt-5.6-luna"},
            {"id": "gpt-5.6-terra"},
            {"id": "github-models/gpt-4o"},
        ]
    }
    with _ModelsProvider(200, listing) as openai:
        ready, _skipped = compose_provider_catalog(
            [_openai_seed(openai.base_url)],
            discover=True,
            allow_insecure_discovery=True,
        )
    blob = json.dumps(
        [{"id": agent.id, "model": agent.model, "base_url": agent.base_url, "credential": agent.credential_name} for agent in ready]
    ).lower()
    assert "gpt-5.5" in {agent.model for agent in ready}
    assert "gpt-5.6-luna" not in blob
    assert "gpt-5.6-terra" not in blob
    assert "github-models" not in blob
    assert "models.github.ai" not in blob
    assert "copilot_github_token" not in blob


def test_discovery_uses_kv_credential_not_process_env() -> None:
    register_credential("OPENAI_API_KEY", "sk-from-kv")
    listing = {"data": [{"id": "gpt-5.5"}]}
    with _ModelsProvider(200, listing) as openai:
        compose_provider_catalog(
            [_openai_seed(openai.base_url)],
            discover=True,
            allow_insecure_discovery=True,
        )
    assert openai.authorization_headers == ["Bearer sk-from-kv"]


def test_seed_provider_catalog_discovers_by_default() -> None:
    register_credential("OPENAI_API_KEY", "sk-default")
    listing = {"data": [{"id": "o4-mini"}, {"id": "text-embedding-3-large"}]}
    with _ModelsProvider(200, listing) as openai:
        report = seed_provider_catalog(
            seed_agents=[_openai_seed(openai.base_url)],
            allow_insecure_discovery=True,
        )
    models = {item["model"] for item in report["ready_agents"]}
    assert "o4-mini" in models
    assert "text-embedding-3-large" not in models
    assert "gpt-5.5" not in models


def test_orchestrator_get_v1_models_lists_gateway_and_worker_ids() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "nim_discovered_chat",
                "nvidia/llama-3.3-nemotron-super-49b-v1.5",
                "mock://nim",
                tags=("reasoning", "coding"),
                provider_name="nvidia_nim",
            ),
            ModelAgent(
                "openai_discovered_chat",
                "gpt-5.5",
                "mock://openai",
                tags=("reasoning",),
                provider_name="openai",
            ),
        ]
    )
    token = "sidecar_token"
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/models",
            headers={"authorization": f"Bearer {token}", "connection": "close"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
    ids = [row["id"] for row in payload["data"]]
    assert payload["object"] == "list"
    assert ids[0] == "contextual-orchestrator"
    assert "nvidia/llama-3.3-nemotron-super-49b-v1.5" in ids
    assert "gpt-5.5" in ids
    assert "gpt-5.6-luna" not in ids
    assert "gpt-5.6-terra" not in ids
    assert all("github" not in item.lower() for item in ids)
    assert all("copilot" not in item.lower() for item in ids)


def test_orchestrator_get_v1_models_requires_inference_bearer() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("solo_worker", "mock-model")])
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token="secret_token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/models",
            headers={"connection": "close"},
            method="GET",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=5)
        assert exc.value.code in {401, 403}
    finally:
        server.shutdown()


if __name__ == "__main__":  # pragma: no cover
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
