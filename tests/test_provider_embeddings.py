"""Provider-backed embeddings stay inside contextual-orchestrator."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.batch_routing import EmbeddingBatchRequest  # noqa: E402
from contextual_orchestrator.cost_router import CostRoutingCoordinator  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    ModelAgent,
    ModelClient,
    NotConfigured,
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode()

    def read(self, *_args: object) -> bytes:
        return self._payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_model_client_embed_many_calls_provider_embeddings_endpoint(monkeypatch) -> None:
    backend = InMemoryCredentialBackend()
    set_backend(backend)
    register_credential("EMBEDDING_KEY", "provider-secret")
    seen: list[tuple[str, dict, str]] = []
    agent = ModelAgent(
        "embedding_agent",
        "text-embedding-model",
        "https://gateway.example/v1",
        credential_key="EMBEDDING_KEY",
        tags=("embedding",),
    )
    client = ModelClient(max_retries=0)
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: object())

    @contextmanager
    def open_provider(request, _destination=None, **_kwargs):
        seen.append((request.full_url, json.loads(request.data), request.headers["Authorization"]))
        yield _Response(
            {
                "data": [
                    {"index": 1, "embedding": [2.0, 3.0]},
                    {"index": 0, "embedding": [0.0, 1.0]},
                ],
                "usage": {"prompt_tokens": 2},
            }
        )

    monkeypatch.setattr(client, "_open_provider", open_provider)
    try:
        assert client.embed_many(agent, ["one", "two"]) == [[0.0, 1.0], [2.0, 3.0]]
    finally:
        set_backend(None)
    assert seen == [
        (
            "https://gateway.example/v1/embeddings",
            {"model": "text-embedding-model", "input": ["one", "two"]},
            "Bearer provider-secret",
        )
    ]


def test_cost_router_uses_embedding_agent_instead_of_heuristic() -> None:
    agent = ModelAgent(
        "embedding_agent",
        "text-embedding-model",
        "https://gateway.example/v1",
        tags=("embedding",),
    )
    calls: list[tuple[str, list[str]]] = []

    def embed_many(selected: ModelAgent, inputs: list[str]) -> list[list[float]]:
        calls.append((selected.model, inputs))
        return [[float(index)] for index, _input in enumerate(inputs)]

    orchestrator = SimpleNamespace(
        candidates=[agent],
        client=SimpleNamespace(embed_many=embed_many),
    )
    coordinator = CostRoutingCoordinator(orchestrator)

    result = coordinator.complete_embeddings_batch(
        ["one", "two"],
        attribution={"provider": "caller-spoof"},
    )

    assert [item["embedding"] for item in result["embeddings"]] == [[0.0], [1.0]]
    assert calls == [("text-embedding-model", ["one", "two"])]
    assert result["model"] == "text-embedding-model"
    assert result["provider"] == "gateway.example"
    assert {record["provider_name"] for record in coordinator.ledger.records()} == {
        "gateway.example"
    }


def test_embedding_client_fails_closed_before_or_after_transport(monkeypatch) -> None:
    client = ModelClient(max_retries=0)
    mock_agent = ModelAgent("mock_embedding", "embedding-model", "mock://embedding")
    assert client.embed_many(mock_agent, []) == []
    with pytest.raises(RuntimeError, match="mock agents"):
        client.embed_many(mock_agent, ["one"])

    backend = InMemoryCredentialBackend()
    set_backend(backend)
    configured_agent = ModelAgent(
        "embedding_agent",
        "embedding-model",
        "https://gateway.example/v1",
        credential_key="MISSING_KEY",
    )
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: object())
    try:
        with pytest.raises(NotConfigured, match="resolvable credential"):
            client.embed_many(configured_agent, ["one"])
    finally:
        set_backend(None)

    monkeypatch.setattr(client, "_send_embeddings", lambda *_args: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(RuntimeError, match="embeddings request failed"):
        client._send_embeddings_with_retry(configured_agent, {"input": ["one"]}, object())


@pytest.mark.parametrize(
    "payload",
    [
        {"data": []},
        {"data": [{"index": "0", "embedding": [1.0]}]},
        {"data": [{"index": 1, "embedding": [1.0]}]},
        {"data": [{"index": 0, "embedding": [float("nan")]}]},
        {
            "data": [
                {"index": 0, "embedding": [1.0]},
                {"index": 0, "embedding": [2.0]},
            ]
        },
    ],
)
def test_embedding_client_rejects_malformed_provider_vectors(monkeypatch, payload) -> None:
    client = ModelClient(max_retries=0)
    agent = ModelAgent("embedding_agent", "embedding-model", "https://gateway.example/v1")

    @contextmanager
    def open_provider(*_args, **_kwargs):
        yield _Response(payload)

    monkeypatch.setattr(client, "_open_provider", open_provider)
    inputs = ["one", "two"] if len(payload.get("data", [])) == 2 else ["one"]
    with pytest.raises(RuntimeError, match="provider embeddings response"):
        client._send_embeddings(agent, {"model": agent.model, "input": inputs}, object())


def test_embedding_model_resolution_covers_server_owned_failure_paths() -> None:
    agent = ModelAgent(
        "embedding_agent",
        "embedding-model",
        "https://gateway.example/v1",
        tags=("embedding",),
    )
    selected = SimpleNamespace(
        candidates=[agent],
        client=SimpleNamespace(embed_many=lambda _agent, inputs: [[1.0] for _ in inputs]),
        select_capability_agent=lambda capability: agent if capability == "embedding" else None,
    )
    coordinator = CostRoutingCoordinator(selected)
    assert coordinator._resolve_embedding_provider_model("contextual-orchestrator") == (
        "gateway.example",
        "embedding-model",
    )
    with pytest.raises(ValueError, match="not configured"):
        coordinator._resolve_embedding_provider_model("other-model")

    standalone = CostRoutingCoordinator(SimpleNamespace(candidates=[]))
    with pytest.raises(ValueError, match="no enabled"):
        standalone._resolve_embedding_provider_model("contextual-orchestrator")
    assert standalone._resolve_embedding_provider_model("explicit-model") == (
        "local",
        "explicit-model",
    )


def test_provider_embedding_backend_rejects_unknown_identity_and_missing_client() -> None:
    agent = ModelAgent(
        "embedding_agent",
        "embedding-model",
        "https://gateway.example/v1",
        tags=("embedding",),
    )
    request = EmbeddingBatchRequest(
        input_text="one",
        model=agent.model,
        provider_name="wrong.example",
    )
    backend = CostRoutingCoordinator(SimpleNamespace(candidates=[agent])).embedding_batch_backend
    with pytest.raises(ValueError, match="not configured"):
        backend._batch_embedder([request])

    request.provider_name = "gateway.example"
    with pytest.raises(RuntimeError, match="no provider embedding client"):
        backend._batch_embedder([request])


def test_provider_json_fetch_is_bounded_and_requires_configured_credentials(monkeypatch) -> None:
    client = ModelClient()
    agent = ModelAgent("catalog_agent", "catalog-model", "https://gateway.example/v1")
    with pytest.raises(ValueError, match="positive integer"):
        client.fetch_json(agent, "https://gateway.example/v1/models", max_bytes=0)

    backend = InMemoryCredentialBackend()
    set_backend(backend)
    secured = ModelAgent(
        "secured_catalog_agent",
        "catalog-model",
        "https://gateway.example/v1",
        credential_key="MISSING_KEY",
    )
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: object())
    try:
        with pytest.raises(NotConfigured, match="resolvable credential"):
            client.fetch_json(secured, "https://gateway.example/v1/models")
    finally:
        set_backend(None)

    @contextmanager
    def open_provider(*_args, **_kwargs):
        yield _Response({"models": ["too large"]})

    monkeypatch.setattr(client, "_open_provider", open_provider)
    backend = InMemoryCredentialBackend()
    backend.set("OPENAI_API_KEY", "provider-key")
    set_backend(backend)
    try:
        with pytest.raises(ValueError, match="maximum size"):
            client.fetch_json(agent, "https://gateway.example/v1/models", max_bytes=1)
    finally:
        set_backend(None)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
