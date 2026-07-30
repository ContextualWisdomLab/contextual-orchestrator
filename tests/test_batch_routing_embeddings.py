"""Embeddings batch-routing coverage: local + pg-llm-batch backends and helpers.

Exercises the cost-hub's embeddings batch path (the repo's sync-vs-batch routing
role): the in-process ``LocalEmbeddingBatchBackend`` (incl. the dependency-free
token-count fallback), the ``PgLlmBatchEmbeddingBackend`` submit/poll/retrieve
flow against a fake async client, and the small helpers (``heuristic_embedding``,
``_extract_embedding``, ``_extract_answer``, ``cheapest_upstream``,
``build_embeddings_jsonl_body``). No network or pg-llm-batch install needed.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import batch_routing as b  # noqa: E402


# --- small helpers -------------------------------------------------------


def test_cheapest_upstream_none_for_empty_candidates() -> None:
    assert b.cheapest_upstream([], price_book={}) is None


def test_extract_answer_empty_choices_is_empty_string() -> None:
    assert b._extract_answer({"choices": []}) == ""
    assert b._extract_answer({"choices": [{"message": {"content": "hi"}}]}) == "hi"


def test_heuristic_embedding_dimension_and_guard() -> None:
    vec = b.heuristic_embedding("고객 이탈", dimension=6)
    assert len(vec) == 6
    with pytest.raises(ValueError):
        b.heuristic_embedding("x", dimension=0)


def test_extract_embedding_parses_and_defaults() -> None:
    assert b._extract_embedding({"data": [{"embedding": [1, 2, 3]}]}) == [1.0, 2.0, 3.0]
    assert b._extract_embedding({}) == []
    assert b._extract_embedding({"data": []}) == []


def test_embedding_request_to_jsonl_line_and_body() -> None:
    req = b.EmbeddingBatchRequest("hello world", custom_id="c1")
    line = req.to_jsonl_line()
    assert line["custom_id"] == "c1"
    body = b.build_embeddings_jsonl_body([req])
    assert "c1" in body and body.startswith("{")


# --- LocalEmbeddingBatchBackend (token-count fallback) -------------------


def test_local_embedding_backend_roundtrip_with_token_fallback() -> None:
    """No token_counter -> the word-count fallback is used; submit/poll/retrieve work."""
    backend = b.LocalEmbeddingBatchBackend(dimension=8)  # token_counter=None -> fallback
    job = backend.submit([b.EmbeddingBatchRequest("two words", custom_id="c1")])
    assert backend.poll(job)["is_complete"] is True
    results = backend.retrieve(job)
    assert len(results) == 1 and len(results[0].embedding) == 8


# --- PgLlmBatchEmbeddingBackend (fake async client) ----------------------


class _FakeClient:
    async def upload_jsonl(self, path, alias):
        return {"id": "file-1"}

    async def create_batch_job(self, input_file_id, alias, *, endpoint, metadata=None):
        return {"id": "batch-1", "status": "validating"}

    async def get_batch_status(self, job_id, alias):
        return {"status": "completed", "is_complete": True, "progress_percentage": 100}

    async def download_results(self, job_id, alias):
        return {
            "success": True,
            "responses": [
                {
                    "custom_id": "c1",
                    "response": {"body": {"data": [{"embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 3}}},
                }
            ],
        }


class _FakeAssembler:
    def assemble(self, lines):
        return "file://assembled"


@pytest.mark.parametrize("assembler", [None, _FakeAssembler()])
def test_pg_embedding_backend_submit_poll_retrieve(assembler) -> None:
    backend = b.PgLlmBatchEmbeddingBackend(_FakeClient(), payload_assembler=assembler)
    job = backend.submit([b.EmbeddingBatchRequest("hi", custom_id="c1")])
    assert job.job_id == "batch-1" and job.request_count == 1
    status = backend.poll(job)
    assert status["is_complete"] is True
    results = backend.retrieve(job)
    assert len(results) == 1
    assert results[0].custom_id == "c1" and results[0].embedding == [0.1, 0.2]
    assert results[0].prompt_tokens == 3


def test_pg_embedding_backend_retrieve_empty_on_failure() -> None:
    class _FailClient(_FakeClient):
        async def download_results(self, job_id, alias):
            return {"success": False}

    backend = b.PgLlmBatchEmbeddingBackend(_FailClient())
    job = backend.submit([b.EmbeddingBatchRequest("hi", custom_id="c1")])
    assert backend.retrieve(job) == []
