"""NIM model discovery — offline fixtures always; live catalog when KV key present."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend  # noqa: E402
from contextual_orchestrator.nim_discovery import (  # noqa: E402
    NIM_CREDENTIAL_NAME,
    discover_nim_models,
    models_to_agent_pool_entries,
    _extract_model_ids,
    _slug_model_id,
)
from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402


def test_extract_model_ids_from_openai_style_payload() -> None:
    payload = {
        "data": [
            {"id": "meta/llama-3.1-70b-instruct"},
            {"id": "google/gemma-2-9b-it"},
            {"id": "meta/llama-3.1-70b-instruct"},  # dedupe
        ]
    }
    ids = _extract_model_ids(payload)
    assert ids == ["google/gemma-2-9b-it", "meta/llama-3.1-70b-instruct"]


def test_slug_model_id_is_multi_word_snake_case() -> None:
    assert "_" in _slug_model_id("gpt4")
    assert _slug_model_id("meta/llama-3.1-70b-instruct").startswith("meta")


def test_discover_without_credential_is_honest_missing_status() -> None:
    set_backend(InMemoryCredentialBackend())
    try:
        report = discover_nim_models()
    finally:
        set_backend(None)
    assert report["measurement_status"] == "credential_missing"
    assert report["model_ids"] == []
    assert report["credential_name"] == NIM_CREDENTIAL_NAME


def test_discover_with_fixture_transport_returns_sorted_ids() -> None:
    backend = InMemoryCredentialBackend()
    backend.set(NIM_CREDENTIAL_NAME, "nvapi-test-not-real")
    set_backend(backend)

    def transport(request, timeout):  # noqa: ANN001
        headers = {k.lower(): v for k, v in request.headers.items()}
        assert "authorization" in headers
        body = json.dumps(
            {"data": [{"id": "z-model"}, {"id": "a-model"}, {"id": "m-model"}]}
        ).encode("utf-8")
        return body

    try:
        report = discover_nim_models(transport=transport)
    finally:
        set_backend(None)

    assert report["measurement_status"] == "live_nim_catalog"
    assert report["model_ids"] == ["a-model", "m-model", "z-model"]
    assert report["model_count"] == 3


def test_models_to_agent_pool_entries_are_loadable_agents() -> None:
    entries = models_to_agent_pool_entries(
        ["meta/llama-3.1-8b-instruct", "google/gemma-2-2b-it"]
    )
    assert len(entries) == 2
    agents = [ModelAgent.from_dict(row) for row in entries]
    orch = TaskOrchestrator(agents)
    # route path still works offline with mock:// default replaced — use mock urls
    mock_agents = [
        ModelAgent(
            agent.id,
            agent.model,
            base_url="mock://local",
            tags=agent.tags,
            priority=agent.priority,
        )
        for agent in agents
    ]
    result = TaskOrchestrator(mock_agents).route_once(
        [{"role": "user", "content": "nim pool route"}]
    )
    assert result["mode"] == "route"
    assert result["answer"]
    assert all(entry["credential_key"] == NIM_CREDENTIAL_NAME for entry in entries)
    assert all("_" in entry["id"] for entry in entries)


def test_extract_model_ids_handles_list_and_non_list_shapes() -> None:
    assert _extract_model_ids(["alpha_model", "beta_model"]) == ["alpha_model", "beta_model"]
    assert _extract_model_ids({"models": [{"model": "x_y"}]}) == ["x_y"]
    assert _extract_model_ids({"data": "not-a-list"}) == []
    assert _extract_model_ids(42) == []


def test_slug_model_id_edge_cases() -> None:
    assert _slug_model_id("!!!") == "unnamed_model"
    assert _slug_model_id("simple") == "simple_model"
    assert "__" not in _slug_model_id("a--b__c")


def test_discover_uses_urllib_when_transport_omitted(monkeypatch) -> None:  # noqa: ANN001
    backend = InMemoryCredentialBackend()
    backend.set(NIM_CREDENTIAL_NAME, "nvapi-test")
    set_backend(backend)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"data": [{"id": "live_fixture_model"}]}).encode("utf-8")

    def fake_urlopen(request, timeout=None, context=None):  # noqa: ANN001
        assert request.get_header("Authorization") or request.headers
        return _Resp()

    monkeypatch.setattr("contextual_orchestrator.nim_discovery.urllib.request.urlopen", fake_urlopen)
    try:
        report = discover_nim_models()
    finally:
        set_backend(None)
    assert report["measurement_status"] == "live_nim_catalog"
    assert report["model_ids"] == ["live_fixture_model"]


def test_live_nim_catalog_when_env_seeded_into_kv() -> None:
    """Optional live check: seed NVIDIA_NIM_API_KEY into KV if present in process env.

    Env is bootstrap transport only; discover_nim_models still reads via get_credential.
    Skips cleanly when the secret is absent so default CI stays hermetic.
    """
    raw = os.environ.get("NVIDIA_NIM_API_KEY", "").strip()
    if not raw:
        return  # optional live path
    backend = InMemoryCredentialBackend()
    backend.set(NIM_CREDENTIAL_NAME, raw)
    set_backend(backend)
    try:
        report = discover_nim_models()
    finally:
        set_backend(None)
    assert report["measurement_status"] == "live_nim_catalog"
    assert report["model_count"] >= 1
    assert all(isinstance(mid, str) and mid for mid in report["model_ids"])


if __name__ == "__main__":  # pragma: no cover
    test_extract_model_ids_from_openai_style_payload()
    test_slug_model_id_is_multi_word_snake_case()
    test_discover_without_credential_is_honest_missing_status()
    test_discover_with_fixture_transport_returns_sorted_ids()
    test_models_to_agent_pool_entries_are_loadable_agents()
    test_live_nim_catalog_when_env_seeded_into_kv()
    print("ok")


def test_role_temperature_defaults_differ_by_paper_role() -> None:
    from contextual_orchestrator.orchestrator import OrchestrationPolicy

    policy = OrchestrationPolicy()
    assert policy.temperature_for_role("verifier") < policy.temperature_for_role("worker")
    assert policy.temperature_for_role("thinker") <= policy.temperature_for_role("worker")
    snap = policy.as_dict()
    assert "role_temperature" in snap
    assert set(snap["role_temperature"]) >= {"thinker", "worker", "verifier", "synthesizer"}


def test_discover_nim_models_cli_prints_credential_missing(capsys) -> None:
    from contextual_orchestrator.__main__ import _discover_nim_models_command
    set_backend(InMemoryCredentialBackend())
    try:
        _discover_nim_models_command([])
    finally:
        set_backend(None)
    out = json.loads(capsys.readouterr().out)
    assert out["measurement_status"] == "credential_missing"
