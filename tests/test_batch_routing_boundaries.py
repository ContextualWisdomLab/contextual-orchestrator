"""Boundary tests for batch routing decisions and embeddings batch backend."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from contextual_orchestrator.batch_routing import (
    BatchRequest,
    EmbeddingBatchRequest,
    LocalBatchBackend,
    PgLlmBatchEmbeddingBackend,
    _extract_answer,
    _extract_embedding,
    build_embeddings_jsonl_body,
    cheapest_upstream,
    heuristic_embedding,
)


class _StaticPriceBook:
    """Price book returning a fixed cost per candidate for tie testing."""

    def __init__(self, cost: float) -> None:
        self._cost = cost
        self.queries: list[tuple[str, str]] = []

    def compute_cost(
        self, provider: str, model: str, prompt_tokens: int, completion_tokens: int
    ) -> tuple[float, str]:
        self.queries.append((provider, model))
        return self._cost, "USD"


def test_cheapest_upstream_returns_none_for_no_candidates() -> None:
    assert cheapest_upstream([], _StaticPriceBook(1.0)) is None


def test_cheapest_upstream_tie_keeps_input_order() -> None:
    first = {"provider": "alpha", "model": "model_one"}
    second = {"provider": "beta", "model": "model_two"}
    best = cheapest_upstream([first, second], _StaticPriceBook(0.5))
    assert best is first  # strict less-than keeps the earlier candidate on ties


def test_local_backend_rejects_invalid_concurrency() -> None:
    with pytest.raises(ValueError, match="max_concurrency"):
        LocalBatchBackend(lambda messages, mode: {}, max_concurrency=0)


def test_extract_answer_handles_missing_choices_and_message() -> None:
    assert _extract_answer({}) == ""
    assert _extract_answer({"choices": []}) == ""
    # A choice without a message body still yields the empty answer.
    assert _extract_answer({"choices": [{}]}) == ""


def test_heuristic_embedding_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        heuristic_embedding("route text", dimension=0)
    with pytest.raises(ValueError, match="dimension must be positive"):
        heuristic_embedding("route text", dimension=-3)


def test_embedding_request_jsonl_line_shape() -> None:
    request = EmbeddingBatchRequest(
        input_text="embed me", model="mock-embedding", custom_id="emb_fixed"
    )
    line = request.to_jsonl_line()
    assert line == {
        "custom_id": "emb_fixed",
        "method": "POST",
        "url": "/v1/embeddings",
        "body": {
            "model": "mock-embedding",
            "input": "embed me",
            "zdr_only": False,
        },
    }
    custom = request.to_jsonl_line("/v1/custom_embeddings")
    assert custom["url"] == "/v1/custom_embeddings"


def test_embedding_request_jsonl_preserves_zdr_policy() -> None:
    request = EmbeddingBatchRequest(input_text="private", zdr_only=True)

    assert request.to_jsonl_line()["body"]["zdr_only"] is True


def test_chat_request_jsonl_preserves_zdr_policy() -> None:
    request = BatchRequest(
        messages=[{"role": "user", "content": "private"}],
        zdr_only=True,
    )

    assert request.to_jsonl_line()["body"]["zdr_only"] is True


def test_build_embeddings_jsonl_body_joins_lines() -> None:
    requests = [
        EmbeddingBatchRequest(input_text="one", custom_id="emb_1"),
        EmbeddingBatchRequest(input_text="two", custom_id="emb_2"),
    ]
    body = build_embeddings_jsonl_body(requests)
    lines = body.splitlines()
    assert len(lines) == 2
    assert '"custom_id": "emb_1"' in lines[0]
    assert '"input": "two"' in lines[1]


class _FakeEmbeddingClient:
    """Async pg-llm-batch double for the embeddings endpoint."""

    def __init__(self) -> None:
        self.uploaded: list[tuple[str, str]] = []
        self.created: list[Dict[str, Any]] = []
        self.status_calls: list[str] = []
        self.downloads: list[str] = []
        self.success = True
        self.responses: List[Dict[str, Any]] = []

    async def upload_jsonl(self, file_path: str, endpoint_alias: str) -> Dict[str, Any]:
        self.uploaded.append((file_path, endpoint_alias))
        return {"id": "file_embed_001"}

    async def create_batch_job(
        self,
        input_file_id: str,
        endpoint_alias: str,
        endpoint: str = "/v1/embeddings",
        metadata: Any = None,
    ) -> Dict[str, Any]:
        self.created.append(
            {
                "input_file_id": input_file_id,
                "endpoint_alias": endpoint_alias,
                "endpoint": endpoint,
                "metadata": metadata,
            }
        )
        return {"id": "batch_embed_777", "status": "validating"}

    async def get_batch_status(self, batch_id: str, endpoint_alias: str) -> Dict[str, Any]:
        self.status_calls.append(batch_id)
        return {"status": "completed", "is_complete": True, "progress_percentage": 100}

    async def download_results(self, batch_id: str, endpoint_alias: str) -> Dict[str, Any]:
        self.downloads.append(batch_id)
        if not self.success:
            return {"success": False}
        return {"success": True, "responses": list(self.responses)}


class _FakeAssembler:
    def __init__(self) -> None:
        self.lines: list[List[Dict[str, Any]]] = []

    def assemble(self, lines: List[Dict[str, Any]]) -> str:
        self.lines.append(lines)
        return "postgres://embedding_payloads/abc"


def test_pg_embedding_backend_full_lifecycle_with_assembler() -> None:
    client = _FakeEmbeddingClient()
    assembler = _FakeAssembler()
    backend = PgLlmBatchEmbeddingBackend(
        client, payload_assembler=assembler, endpoint="/v1/embeddings"
    )

    requests = [
        EmbeddingBatchRequest(
            input_text="first passage",
            model="mock-embedding",
            custom_id="emb_a",
            attribution={"tenant": "acme"},
        ),
        EmbeddingBatchRequest(input_text="second passage", custom_id="emb_b"),
    ]
    job = backend.submit(requests, metadata={"purpose": "nightly_index"})
    assert job.job_id == "batch_embed_777"
    assert job.backend == "pg-llm-batch"
    assert job.status == "validating"
    assert job.request_count == 2
    # The assembler received OpenAI embeddings JSONL lines and produced the upload.
    assert len(assembler.lines) == 1
    assert assembler.lines[0][0]["custom_id"] == "emb_a"
    assert client.uploaded == [("postgres://embedding_payloads/abc", "default")]
    assert client.created[0]["endpoint"] == "/v1/embeddings"
    assert client.created[0]["metadata"] == {"purpose": "nightly_index"}

    status = backend.poll(job)
    assert status == {
        "job_id": "batch_embed_777",
        "status": "completed",
        "is_complete": True,
        "progress_percentage": 100,
    }

    # Results arrive out of order; retrieve must restore submission order.
    client.responses = [
        {
            "custom_id": "emb_b",
            "response": {
                "body": {
                    "data": [{"embedding": [0.25, -0.75]}],
                    "usage": {"prompt_tokens": 4},
                }
            },
        },
        {
            "custom_id": "emb_a",
            "response": {
                "body": {
                    "data": [{"embedding": ["0.5", 1]}],
                    "usage": {"prompt_tokens": 9},
                }
            },
        },
    ]
    items = backend.retrieve(job)
    assert [item.custom_id for item in items] == ["emb_a", "emb_b"]
    assert items[0].index == 0 and items[1].index == 1
    assert items[0].embedding == [0.5, 1.0]  # string embeddings normalized to floats
    assert items[0].prompt_tokens == 9
    assert items[0].model == "mock-embedding"
    assert items[1].model == "contextual-orchestrator"


def test_pg_embedding_backend_memory_fallback_and_defaults() -> None:
    client = _FakeEmbeddingClient()
    backend = PgLlmBatchEmbeddingBackend(client, endpoint_alias="nim-east")
    requests = [EmbeddingBatchRequest(input_text="solo input", custom_id="emb_solo")]
    job = backend.submit(requests)
    assert job.status == "validating"
    file_path, alias = client.uploaded[0]
    assert alias == "nim-east"
    assert file_path.startswith("memory://")

    status = backend.poll(job)
    assert status["job_id"] == "batch_embed_777"
    assert status["progress_percentage"] == 100

    client.responses = [
        {
            "custom_id": "emb_unknown",
            "response": {"body": {"usage": {}}},
        },
        {
            "custom_id": "",
            "response": {"body": {}},
        },
    ]
    items = backend.retrieve(job)
    assert len(items) == 2
    # Untracked ids fall back to positional indexes and default model naming.
    assert [item.index for item in items] == [0, 1]
    assert all(item.model == "contextual-orchestrator" for item in items)
    assert items[1].embedding == []


def test_pg_embedding_backend_failed_download_returns_empty() -> None:
    client = _FakeEmbeddingClient()
    client.success = False
    backend = PgLlmBatchEmbeddingBackend(client)
    job = backend.submit([EmbeddingBatchRequest(input_text="never retrieved")])
    assert backend.retrieve(job) == []
    assert client.downloads == [job.job_id]


def test_extract_embedding_normalizes_values() -> None:
    assert _extract_embedding({}) == []
    assert _extract_embedding({"data": []}) == []
    assert _extract_embedding({"data": [{}]}) == []
    vector = _extract_embedding({"data": [{"embedding": [1, "2.5"]}]} )
    assert vector == [1.0, 2.5]


def test_local_chat_backend_registry_backed_results_round_trip() -> None:
    from contextual_orchestrator.batch_job_registry import JobRegistryFactory
    from tests.test_batch_job_registry import FakeValkeyClient

    registry = JobRegistryFactory(FakeValkeyClient())
    backend = LocalBatchBackend(
        lambda messages, mode, model: {
            "answer": f"ran-{mode}-{model}",
            "mode": mode,
        },
        max_concurrency=2,
        job_registry=registry,
    )
    requests = [
        BatchRequest(messages=[{"role": "user", "content": "a"}], custom_id="req_a"),
        BatchRequest(messages=[{"role": "user", "content": "b"}], custom_id="req_b"),
        BatchRequest(messages=[{"role": "user", "content": "c"}], custom_id="req_c"),
    ]
    job = backend.submit(requests)
    assert job.request_count == 3
    results = backend.retrieve(job)
    assert [item.custom_id for item in results] == ["req_a", "req_b", "req_c"]
    assert all(item.answer == "ran-auto-contextual-orchestrator" for item in results)
