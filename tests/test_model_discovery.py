"""Product auto-discovery: KV keys, live catalog, NIM floor, no env fallback."""

from __future__ import annotations

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    FLOOR_DEFAULT_MODEL_ID,
    FLOOR_SMALL_MODEL_ID,
    ModelAgent,
    TaskOrchestrator,
    apply_discovered_pool,
    discover_model_catalog,
    get_credential,
    list_served_models,
)
from contextual_orchestrator.credentials import InMemoryCredentialBackend, register_credential, set_backend  # noqa: E402
from contextual_orchestrator.model_discovery import (  # noqa: E402
    DISCOVERY_CREDENTIAL_NAMES,
    PROVIDER_ENDPOINTS,
    allocate_compute_tags,
    normalize_catalog_payload,
    registered_discovery_keys,
)


def _backend() -> None:
    set_backend(InMemoryCredentialBackend())


def _openai_payload(*model_ids: str) -> dict:
    return {"object": "list", "data": [{"id": model_id, "owned_by": "org"} for model_id in model_ids]}


def test_unregistered_keys_are_not_read_from_environ() -> None:
    _backend()
    os.environ["OPENAI_API_KEY"] = "sk-env-must-not-count"
    os.environ["NVIDIA_NIM_API_KEY"] = "nvapi-env-must-not-count"
    try:
        assert get_credential("OPENAI_API_KEY") is None
        assert registered_discovery_keys() == ()
        snapshot = discover_model_catalog(fetcher=lambda endpoint, key: (_ for _ in ()).throw(AssertionError(key)))
        assert snapshot.used_floor is True
        assert snapshot.source == "floor"
        assert {model.model_id for model in snapshot.models} == {
            FLOOR_DEFAULT_MODEL_ID,
            FLOOR_SMALL_MODEL_ID,
        }
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("NVIDIA_NIM_API_KEY", None)
        set_backend(None)


def test_live_catalog_is_not_the_two_nim_floor_ids() -> None:
    _backend()
    register_credential("OPENAI_API_KEY", "sk-test")
    register_credential("OPENROUTER_API_KEY", "or-test")

    def fetch(endpoint, key):
        assert key in {"sk-test", "or-test"}
        if endpoint.credential_name == "OPENAI_API_KEY":
            return _openai_payload("gpt-4.1", "text-embedding-3-large", "whisper-1")
        if endpoint.credential_name == "OPENROUTER_API_KEY":
            return {
                "data": [
                    {
                        "id": "anthropic/claude-sonnet",
                        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                    },
                    {
                        "id": "anthropic/claude-sonnet:free",
                        "pricing": {"prompt": "0", "completion": "0"},
                    },
                ]
            }
        raise AssertionError(endpoint.credential_name)

    snapshot = discover_model_catalog(fetcher=fetch)
    ids = [model.model_id for model in snapshot.models]
    assert snapshot.used_floor is False
    assert snapshot.source == "live"
    assert FLOOR_DEFAULT_MODEL_ID not in ids
    assert FLOOR_SMALL_MODEL_ID not in ids
    assert "gpt-4.1" in ids
    assert "anthropic/claude-sonnet" in ids
    assert "anthropic/claude-sonnet:free" in ids
    assert "text-embedding-3-large" not in ids
    assert "whisper-1" not in ids
    set_backend(None)


def test_empty_live_fetch_falls_back_to_nim_floor_only() -> None:
    _backend()
    register_credential("NVIDIA_NIM_API_KEY", "nvapi-test")
    register_credential("BYTEZ_API_KEY", "bytez-test")

    def fetch(endpoint, key):
        if endpoint.credential_name == "NVIDIA_NIM_API_KEY":
            return {"data": []}
        return {"models": []}

    snapshot = discover_model_catalog(fetcher=fetch)
    assert snapshot.used_floor is True
    assert [model.model_id for model in snapshot.models] == [
        FLOOR_DEFAULT_MODEL_ID,
        FLOOR_SMALL_MODEL_ID,
    ]
    assert all(model.discovery_source == "floor" for model in snapshot.models)
    set_backend(None)


def test_failed_provider_does_not_abort_other_catalogs() -> None:
    _backend()
    register_credential("OPENAI_API_KEY", "sk-test")
    register_credential("BYTEZ_API_KEY", "bytez-test")

    def fetch(endpoint, key):
        if endpoint.credential_name == "OPENAI_API_KEY":
            raise TimeoutError("upstream timeout Bearer sk-test")
        return {"models": [{"model": "bytez-llama-3", "owned_by": "bytez"}]}

    snapshot = discover_model_catalog(fetcher=fetch)
    assert snapshot.used_floor is False
    assert [model.model_id for model in snapshot.models] == ["bytez-llama-3"]
    assert "OPENAI_API_KEY" in snapshot.provider_errors
    assert "sk-test" not in snapshot.provider_errors["OPENAI_API_KEY"]
    assert "[REDACTED]" in snapshot.provider_errors["OPENAI_API_KEY"]
    set_backend(None)


def test_apply_keeps_seed_when_no_key_is_registered() -> None:
    _backend()
    seed = [ModelAgent("general_agent", "mock-generalist", tags=("reasoning",))]
    orchestrator = TaskOrchestrator(seed)
    snapshot = apply_discovered_pool(orchestrator)
    assert snapshot.source == "seed"
    assert snapshot.used_floor is False
    assert orchestrator.agents[0].id == "general_agent"
    set_backend(None)


def test_apply_replaces_seed_with_discovered_workers() -> None:
    _backend()
    register_credential("NVIDIA_NIM_API_KEY", "nvapi-test")
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning",))])

    def fetch(endpoint, key):
        return _openai_payload(
            "nvidia/nemotron-3-ultra-550b-a55b",
            "nvidia/nemotron-3-super-120b-a12b",
            "meta/llama-3.1-70b-instruct",
        )

    snapshot = apply_discovered_pool(orchestrator, fetcher=fetch)
    assert snapshot.used_floor is False
    models = {agent.model for agent in orchestrator.agents}
    assert models == {
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/nemotron-3-super-120b-a12b",
        "meta/llama-3.1-70b-instruct",
    }
    assert all(agent.credential_key == "NVIDIA_NIM_API_KEY" for agent in orchestrator.agents)
    assert all(agent.discovery_source == "live" for agent in orchestrator.agents)
    served = list_served_models(orchestrator)
    served_ids = [row["id"] for row in served["data"]]
    assert served["object"] == "list"
    assert served_ids[0] == "contextual-orchestrator"
    assert "meta/llama-3.1-70b-instruct" in served_ids
    set_backend(None)


def test_compute_allocation_covers_fugu_and_trinity_roles() -> None:
    small = set(allocate_compute_tags(FLOOR_SMALL_MODEL_ID))
    large = set(allocate_compute_tags(FLOOR_DEFAULT_MODEL_ID))
    assert {"cheap", "fallback", "coding"} <= small
    assert {"planning", "writing", "review", "verification", "reasoning"} <= large


def test_malformed_catalog_does_not_invent_models() -> None:
    endpoint = PROVIDER_ENDPOINTS["OPENAI_API_KEY"]
    assert normalize_catalog_payload("not-json-object", endpoint) == []
    assert normalize_catalog_payload({"data": [None, 3, {"id": ""}]}, endpoint) == []
    duplicates = normalize_catalog_payload(
        {"data": [{"id": "gpt-4.1"}, {"id": "gpt-4.1"}, {"id": "gpt-4.1-mini"}]},
        endpoint,
    )
    assert [model.model_id for model in duplicates] == ["gpt-4.1", "gpt-4.1-mini"]


def test_all_five_discovery_names_are_wired() -> None:
    assert DISCOVERY_CREDENTIAL_NAMES == (
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "BYTEZ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    )


if __name__ == "__main__":  # pragma: no cover
    test_unregistered_keys_are_not_read_from_environ()
    test_live_catalog_is_not_the_two_nim_floor_ids()
    test_empty_live_fetch_falls_back_to_nim_floor_only()
    test_failed_provider_does_not_abort_other_catalogs()
    test_apply_keeps_seed_when_no_key_is_registered()
    test_apply_replaces_seed_with_discovered_workers()
    test_compute_allocation_covers_fugu_and_trinity_roles()
    test_malformed_catalog_does_not_invent_models()
    test_all_five_discovery_names_are_wired()
    print("ok")
