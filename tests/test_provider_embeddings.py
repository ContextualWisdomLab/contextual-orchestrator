"""Provider-backed embeddings stay inside contextual-orchestrator."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

from contextual_orchestrator.credentials import InMemoryCredentialBackend, register_credential, set_backend
from contextual_orchestrator.cost_router import CostRoutingCoordinator
from contextual_orchestrator.orchestrator import ModelAgent, ModelClient


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode()

    def read(self) -> bytes:
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

    result = coordinator.complete_embeddings_batch(["one", "two"], model="text-embedding-model")

    assert [item["embedding"] for item in result["embeddings"]] == [[0.0], [1.0]]
    assert calls == [("text-embedding-model", ["one", "two"])]
