from __future__ import annotations

import pytest

from contextual_orchestrator.batch_routing import (
    EmbeddingBatchRequest,
    ProviderEmbeddingBatchBackend,
    UnavailableEmbeddingBatchBackend,
)


class _Backend(ProviderEmbeddingBatchBackend):
    def _post(self, model: str, inputs: list[str]) -> dict:
        assert model == "embed-model"
        assert inputs == ["first", "second"]
        return {"data": [{"index": 1, "embedding": [2]}, {"index": 0, "embedding": [1]}]}


class _InvalidBackend(_Backend):
    def _post(self, model: str, inputs: list[str]) -> dict:
        return {"data": [{"index": 0, "embedding": []}, {"index": 1, "embedding": [2]}]}


def _requests() -> list[EmbeddingBatchRequest]:
    return [
        EmbeddingBatchRequest(custom_id="a", input_text="first", model="embed-model"),
        EmbeddingBatchRequest(custom_id="b", input_text="second", model="embed-model"),
    ]


def test_provider_embedding_backend_orders_vectors_and_records_provider() -> None:
    backend = _Backend("https://gateway.example/v1", {"embed-model"})
    requests = _requests()
    job = backend.submit(requests)
    assert job.status == "completed"
    assert [item.embedding for item in backend.retrieve(job)] == [[1.0], [2.0]]
    assert all(request.attribution["provider"] == "gateway.example" for request in requests)


def test_provider_embedding_backend_rejects_invalid_response() -> None:
    with pytest.raises(RuntimeError, match="invalid vector"):
        _InvalidBackend("https://gateway.example/v1", {"embed-model"}).submit(_requests())


def test_unavailable_embedding_backend_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="not configured"):
        UnavailableEmbeddingBatchBackend().submit(_requests())
