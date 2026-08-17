"""Bootstrap: register org secrets into the KV and compose a ready agent pool.

Env is bootstrap transport only (docs/kv-credentials.md). A missing secret skips
that upstream and keeps the rest serving — NotConfigured is per-agent, never a
process crash. Live GET /v1/models is the primary catalog after each secret is in the KV;
the paper-justified static seed is fallback only (docs/doctoring/provider-catalog.md).
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    get_credential,
    set_backend,
)
from contextual_orchestrator.provider_catalog import (  # noqa: E402
    ORG_CREDENTIAL_NAMES,
    compose_provider_catalog,
    discover_provider_models,
    parse_models_list,
    persist_catalog_to_agents_db,
    register_org_credentials_from_env,
    seed_provider_catalog,
)


@pytest.fixture(autouse=True)
def _fresh_backend():
    set_backend(InMemoryCredentialBackend())
    saved = {name: os.environ.pop(name, None) for name in ORG_CREDENTIAL_NAMES}
    try:
        yield
    finally:
        set_backend(None)
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_register_org_credentials_skips_missing_and_does_not_crash() -> None:
    os.environ["OPENAI_API_KEY"] = "sk-openai-present"
    os.environ["NVIDIA_NIM_API_KEY"] = "nvapi-present"
    report = register_org_credentials_from_env(skip_missing=True)
    assert report["registered"] == ["NVIDIA_NIM_API_KEY", "OPENAI_API_KEY"]
    assert "BYTEZ_API_KEY" in report["skipped"]
    assert "OPENROUTER_API_KEY" in report["skipped"]
    assert "NVIDIA_NIM_API_KEY_SUB" in report["skipped"]
    assert get_credential("OPENAI_API_KEY") == "sk-openai-present"
    assert get_credential("BYTEZ_API_KEY") is None


def test_register_org_credentials_can_require_every_name() -> None:
    with pytest.raises(RuntimeError, match="NVIDIA_NIM_API_KEY"):
        register_org_credentials_from_env(skip_missing=False)


def test_discover_provider_models_returns_empty_without_key_or_public_https() -> None:
    assert discover_provider_models("https://api.openai.com/v1", "OPENAI_API_KEY") == []
    os.environ["OPENAI_API_KEY"] = "sk-present"
    register_org_credentials_from_env(skip_missing=True)
    assert discover_provider_models("not-a-url", "OPENAI_API_KEY") == []
    assert discover_provider_models("http://127.0.0.1:9", "OPENAI_API_KEY", allow_insecure=False) == []
    assert discover_provider_models("file:///etc/passwd", "OPENAI_API_KEY", allow_insecure=True) == []


def test_discovered_agent_id_truncates_and_avoids_collisions() -> None:
    from contextual_orchestrator.provider_catalog import _discovered_agent_id

    long_model = "x" * 120
    short_id = _discovered_agent_id("openai", long_model, set())
    assert len(short_id) <= 80
    first = _discovered_agent_id("openai", "o4-mini", set())
    second = _discovered_agent_id("openai", "o4-mini", {first})
    assert first != second
    assert first.startswith("openai_")


def test_parse_models_list_dedupes_repeated_chat_ids() -> None:
    models = parse_models_list({"data": [{"id": "gpt-5.5"}, {"id": "gpt-5.5"}]})
    assert models == ["gpt-5.5"]


def test_register_org_credentials_never_reads_absent_names_as_empty() -> None:
    report = register_org_credentials_from_env(skip_missing=True)
    assert report["registered"] == []
    assert set(report["skipped"]) == set(ORG_CREDENTIAL_NAMES)
    for name in ORG_CREDENTIAL_NAMES:
        assert get_credential(name) is None


def test_compose_skips_agents_whose_credential_is_missing() -> None:
    os.environ["OPENAI_API_KEY"] = "sk-only-openai"
    register_org_credentials_from_env(skip_missing=True)
    seed = [
        ModelAgent(
            "openai_primary_agent",
            "gpt-5.5",
            "https://api.openai.com/v1",
            credential_key="OPENAI_API_KEY",
            tags=("reasoning",),
        ),
        ModelAgent(
            "bytez_primary_agent",
            "Qwen/Qwen3-4B",
            "https://api.bytez.com/models/v2/openai/v1",
            credential_key="BYTEZ_API_KEY",
            tags=("coding",),
        ),
    ]
    ready, skipped = compose_provider_catalog(seed, discover=False)
    assert [agent.id for agent in ready] == ["openai_primary_agent"]
    assert [row["id"] for row in skipped] == ["bytez_primary_agent"]
    assert skipped[0]["reason"] == "credential_missing"


def test_compose_persists_ready_agents_to_agents_db() -> None:
    os.environ["OPENAI_API_KEY"] = "sk-persist"
    register_org_credentials_from_env(skip_missing=True)
    seed = [
        ModelAgent(
            "openai_primary_agent",
            "gpt-5.5",
            "https://api.openai.com/v1",
            credential_key="OPENAI_API_KEY",
            tags=("reasoning", "writing"),
        )
    ]
    ready, _skipped = compose_provider_catalog(seed, discover=False)
    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "agents.db")
        persist_catalog_to_agents_db(ready, db_path)
        restarted = TaskOrchestrator(
            [ModelAgent("placeholder_agent", "mock-hold", "mock://hold")],
            agents_db=db_path,
        )
        assert any(agent.id == "openai_primary_agent" for agent in restarted.agents)
        assert any(agent.model == "gpt-5.5" for agent in restarted.agents)


def test_parse_models_list_keeps_chat_ids_and_drops_non_chat() -> None:
    payload = {
        "object": "list",
        "data": [
            {"id": "gpt-5.5", "object": "model"},
            {"id": "text-embedding-3-large", "object": "model"},
            {"id": "whisper-1", "object": "model"},
            {"id": "dall-e-3", "object": "model"},
            {"id": "tts-1", "object": "model"},
            {"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5"},
            {"id": "gpt-5.6-luna"},
        ],
    }
    models = parse_models_list(payload)
    assert "gpt-5.5" in models
    assert "nvidia/llama-3.3-nemotron-super-49b-v1.5" in models
    assert "text-embedding-3-large" not in models
    assert "whisper-1" not in models
    assert "dall-e-3" not in models
    assert "tts-1" not in models
    assert "gpt-5.6-luna" not in models


def test_parse_models_list_is_exception_robust_on_malformed_payloads() -> None:
    assert parse_models_list(None) == []
    assert parse_models_list("not-json-object") == []
    assert parse_models_list({"data": "nope"}) == []
    assert parse_models_list({"data": [None, 3, {"id": ""}]}) == []


class _ModelsProvider:
    """Serves GET /models with a scripted body (OpenAI list shape)."""

    def __init__(self, status: int, body: object) -> None:
        self.status = status
        self.body = body
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                raw = json.dumps(outer.body).encode("utf-8") if not isinstance(outer.body, bytes) else outer.body
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


def test_discover_provider_models_registers_chat_ids_from_list_api() -> None:
    os.environ["OPENAI_API_KEY"] = "sk-discover"
    register_org_credentials_from_env(skip_missing=True)
    listing = {"data": [{"id": "gpt-5.5"}, {"id": "gpt-5.5-mini"}, {"id": "text-embedding-3-small"}]}
    with _ModelsProvider(200, listing) as provider:
        models = discover_provider_models(provider.base_url, "OPENAI_API_KEY", allow_insecure=True)
    assert models == ["gpt-5.5", "gpt-5.5-mini"]


def test_discover_provider_models_keeps_static_seed_when_list_api_fails() -> None:
    os.environ["OPENAI_API_KEY"] = "sk-discover-fail"
    register_org_credentials_from_env(skip_missing=True)
    with _ModelsProvider(404, {"error": "no list"}) as provider:
        models = discover_provider_models(provider.base_url, "OPENAI_API_KEY", allow_insecure=True)
    assert models == []
    with _ModelsProvider(200, b"<<<not-json") as provider:
        models = discover_provider_models(provider.base_url, "OPENAI_API_KEY", allow_insecure=True)
    assert models == []


def test_seed_provider_catalog_discovers_and_skips_partial_keys() -> None:
    os.environ["OPENAI_API_KEY"] = "sk-seed"
    listing = {"data": [{"id": "gpt-5.5"}, {"id": "o4-mini"}]}
    with _ModelsProvider(200, listing) as provider:
        seed = [
            ModelAgent(
                "openai_primary_agent",
                "gpt-5.5",
                provider.base_url,
                credential_key="OPENAI_API_KEY",
                tags=("reasoning",),
                provider_name="openai",
            ),
            ModelAgent(
                "openrouter_primary_agent",
                "anthropic/claude-sonnet-4",
                "https://openrouter.ai/api/v1",
                credential_key="OPENROUTER_API_KEY",
                tags=("review",),
                provider_name="openrouter",
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "pool.db")
            report = seed_provider_catalog(
                seed_agents=seed,
                agents_db=db_path,
                discover=True,
                allow_insecure_discovery=True,
            )
    assert "OPENAI_API_KEY" in report["registered_credentials"]
    assert "OPENROUTER_API_KEY" in report["skipped_credentials"]
    ready_ids = {item["id"] for item in report["ready_agents"]}
    assert "openrouter_primary_agent" not in ready_ids
    assert any(item["model"] == "o4-mini" for item in report["ready_agents"])
    assert any(item["model"] == "gpt-5.5" for item in report["ready_agents"])
    assert all("github" not in item["model"].lower() for item in report["ready_agents"])


if __name__ == "__main__":  # pragma: no cover
    import traceback

    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except TypeError:
                # pytest fixtures are not available in the script runner
                traceback.print_exc()
                raise
            print(f"ok {name}")
    print("ok")
