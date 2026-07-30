"""Embeddings batch routing: heuristic embedding, local + pg backends, helpers.

Covers the offline embeddings path — ``heuristic_embedding``, the in-process
``LocalEmbeddingBatchBackend``, the ``PgLlmBatchEmbeddingBackend`` (via an async
fake client), and the module helpers — with no Postgres and no external service.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.batch_routing import (  # noqa: E402
    BatchJob,
    BatchRequest,
    EmbeddingBatchRequest,
    LocalEmbeddingBatchBackend,
    PgLlmBatchBackend,
    PgLlmBatchEmbeddingBackend,
    RoutingHints,
    _extract_answer,
    _extract_embedding,
    build_embeddings_jsonl_body,
    cheapest_upstream,
    heuristic_embedding,
)


# --- module helpers ---------------------------------------------------------


def test_cheapest_upstream_returns_none_for_no_candidates() -> None:
    """Cheapest upstream returns none for no candidates."""
    # empty candidates short-circuit before the price book is consulted
    assert cheapest_upstream([], None) is None


def test_extract_answer_empty_choices_is_blank() -> None:
    """Extract answer empty choices is blank."""
    assert _extract_answer({"choices": []}) == ""
    assert _extract_answer({}) == ""


def test_extract_embedding_reads_first_vector_or_empty() -> None:
    """Extract embedding reads first vector or empty."""
    assert _extract_embedding({"data": [{"embedding": [0.1, 0.2, 0.3]}]}) == [0.1, 0.2, 0.3]
    assert _extract_embedding({}) == []


def test_heuristic_embedding_is_deterministic_and_ranged() -> None:
    """Heuristic embedding is deterministic and ranged."""
    vector = heuristic_embedding("hello", dimension=8)
    assert len(vector) == 8
    assert all(-1.0 <= value <= 1.0 for value in vector)
    assert heuristic_embedding("hello", dimension=8) == vector


def test_heuristic_embedding_rejects_non_positive_dimension() -> None:
    """Heuristic embedding rejects non positive dimension."""
    with pytest.raises(ValueError):
        heuristic_embedding("hello", dimension=0)


def test_embedding_request_to_jsonl_line_shape() -> None:
    """Embedding request to jsonl line shape."""
    line = EmbeddingBatchRequest(input_text="hi", model="embed-x", custom_id="e1").to_jsonl_line(
        "/v1/embeddings"
    )
    assert line["custom_id"] == "e1"
    assert line["url"] == "/v1/embeddings"
    assert line["body"] == {"model": "embed-x", "input": "hi"}


def test_build_embeddings_jsonl_body_is_newline_delimited() -> None:
    """Build embeddings jsonl body is newline delimited."""
    body = build_embeddings_jsonl_body(
        [
            EmbeddingBatchRequest(input_text="hi", model="embed-x", custom_id="e1"),
            EmbeddingBatchRequest(input_text="yo", model="embed-x", custom_id="e2"),
        ]
    )
    assert body.count("\n") == 1
    assert '"custom_id": "e1"' in body


# --- local embeddings backend ----------------------------------------------


def test_local_embedding_backend_token_fallback_counts_words() -> None:
    """Local embedding backend token fallback counts words."""
    backend = LocalEmbeddingBatchBackend(dimension=4)  # no token_counter -> word fallback
    job = backend.submit(
        [EmbeddingBatchRequest(input_text="one two three", model="embed-x", custom_id="e1")]
    )
    assert backend.poll(job)["is_complete"] is True
    items = backend.retrieve(job)
    assert len(items) == 1
    assert items[0].prompt_tokens == 3
    assert len(items[0].embedding) == 4


class _FakeTokenCounter:
    """Token counter returning a fixed count, exercising the counted path."""

    def count_text(self, text: str, model: str) -> int:
        """Return a constant token count regardless of input."""
        return 42


def test_local_embedding_backend_uses_injected_token_counter() -> None:
    """Local embedding backend uses injected token counter."""
    backend = LocalEmbeddingBatchBackend(token_counter=_FakeTokenCounter(), dimension=4)
    job = backend.submit(
        [EmbeddingBatchRequest(input_text="anything", model="embed-x", custom_id="e1")]
    )
    assert backend.retrieve(job)[0].prompt_tokens == 42


def test_local_embedding_backend_retrieve_unknown_job_is_empty() -> None:
    """Local embedding backend retrieve unknown job is empty."""
    backend = LocalEmbeddingBatchBackend()
    unknown = BatchJob(job_id="missing", backend="local", status="completed", request_count=0)
    assert backend.retrieve(unknown) == []


# --- pg-llm-batch embeddings backend ---------------------------------------


class _FakeEmbeddingClient:
    """Async pg-llm-batch client fake returning one embedding response."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def upload_jsonl(self, file_path, endpoint_alias, purpose="batch"):
        """Record the call and return a stub uploaded-file id."""
        self.calls.append("upload_jsonl")
        return {"id": "file-emb"}

    async def create_batch_job(
        self, input_file_id, endpoint_alias, endpoint="/v1/embeddings", metadata=None
    ):
        """Record the call and return a stub batch-job id."""
        self.calls.append("create_batch_job")
        assert input_file_id == "file-emb"
        return {"id": "batch-emb", "status": "validating"}

    async def get_batch_status(self, batch_id, endpoint_alias):
        """Return a completed status."""
        self.calls.append("get_batch_status")
        return {"status": "completed", "is_complete": True, "progress_percentage": 100}

    async def download_results(self, batch_id, endpoint_alias):
        """Return one embedding response body."""
        self.calls.append("download_results")
        return {
            "success": True,
            "responses": [
                {
                    "custom_id": "e1",
                    "response": {
                        "body": {"data": [{"embedding": [0.5, 0.25]}], "usage": {"prompt_tokens": 7}}
                    },
                }
            ],
        }


def test_pg_embedding_backend_submit_poll_retrieve() -> None:
    """Pg embedding backend submit poll retrieve."""
    client = _FakeEmbeddingClient()
    backend = PgLlmBatchEmbeddingBackend(client, endpoint_alias="prod_gateway")
    job = backend.submit(
        [EmbeddingBatchRequest(input_text="embed me", model="embed-x", custom_id="e1")],
        metadata={"routing_reason": "bulk"},
    )
    assert job.backend == "pg-llm-batch"
    assert job.job_id == "batch-emb"
    assert backend.poll(job)["is_complete"] is True
    items = backend.retrieve(job)
    assert len(items) == 1
    assert items[0].custom_id == "e1"
    assert items[0].embedding == [0.5, 0.25]
    assert items[0].prompt_tokens == 7
    assert items[0].model == "embed-x"
    assert client.calls == ["upload_jsonl", "create_batch_job", "get_batch_status", "download_results"]


def test_pg_embedding_backend_incomplete_download_returns_empty() -> None:
    """Pg embedding backend incomplete download returns empty."""
    class _IncompleteClient(_FakeEmbeddingClient):
        async def download_results(self, batch_id, endpoint_alias):
            """Report an unsuccessful download."""
            return {"success": False}

    backend = PgLlmBatchEmbeddingBackend(_IncompleteClient())
    job = backend.submit([EmbeddingBatchRequest(input_text="x", model="embed-x", custom_id="e1")])
    assert backend.retrieve(job) == []


class _FakeAssembler:
    """Payload assembler stand-in that records the assembled JSONL lines."""

    def __init__(self) -> None:
        self.assembled = None

    def assemble(self, lines) -> str:
        """Record the lines and return a stub file path."""
        self.assembled = lines
        return "file:///tmp/embeddings.jsonl"


def test_pg_embedding_backend_uses_payload_assembler_when_provided() -> None:
    """Pg embedding backend uses payload assembler when provided."""
    assembler = _FakeAssembler()
    backend = PgLlmBatchEmbeddingBackend(_FakeEmbeddingClient(), payload_assembler=assembler)
    backend.submit([EmbeddingBatchRequest(input_text="hi", model="embed-x", custom_id="e1")])
    assert assembler.assembled is not None
    assert assembler.assembled[0]["custom_id"] == "e1"


def test_completions_backend_uses_payload_assembler_when_provided() -> None:
    """Completions backend uses payload assembler when provided."""
    assembler = _FakeAssembler()
    backend = PgLlmBatchBackend(_FakeEmbeddingClient(), payload_assembler=assembler)
    backend.submit(
        [BatchRequest(messages=[{"role": "user", "content": "hi"}], custom_id="a", model="gpt-x")]
    )
    assert assembler.assembled is not None
    assert assembler.assembled[0]["custom_id"] == "a"


# --- routing hints from a loose mapping -------------------------------------


def test_routing_hints_from_mapping_normalizes_values() -> None:
    """Routing hints from mapping normalizes values."""
    hints = RoutingHints.from_mapping(
        {"channel": "Batch", "latency_tolerant": True, "priority": "Bulk"}
    )
    assert hints.channel == "batch"
    assert hints.latency_tolerant is True
    assert hints.priority == "bulk"


def test_routing_hints_from_mapping_defaults_when_empty() -> None:
    """Routing hints from mapping defaults when empty."""
    hints = RoutingHints.from_mapping(None)
    assert hints.channel is None
    assert hints.priority == "normal"
