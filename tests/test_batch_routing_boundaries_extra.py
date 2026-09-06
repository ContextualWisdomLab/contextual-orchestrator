"""Boundary coverage for the explicit local embedding implementation seam."""

from __future__ import annotations

import pytest

from contextual_orchestrator.batch_routing import EmbeddingBatchRequest, LocalEmbeddingBatchBackend


class _Counter:
    def count_text(self, text: str, model: str) -> int:
        del text, model
        return 42


def test_local_backend_without_embedder_fails_closed() -> None:
    backend = LocalEmbeddingBatchBackend(token_counter=_Counter())
    request = EmbeddingBatchRequest(
        custom_id="row-1", model="m", input_text="semantic text"
    )
    with pytest.raises(RuntimeError, match="explicit embedding implementation"):
        backend.submit([request])


def test_local_backend_without_token_counter_still_fails_closed() -> None:
    backend = LocalEmbeddingBatchBackend(embedder=lambda text: [float(len(text))])
    request = EmbeddingBatchRequest(
        custom_id="row-1", model="m", input_text="semantic text"
    )
    with pytest.raises(RuntimeError, match="authoritative embedding tokenizer"):
        backend.submit([request])


def test_local_backend_requires_both_explicit_semantics_and_accounting() -> None:
    backend = LocalEmbeddingBatchBackend(
        embedder=lambda text: [float(len(text))], token_counter=_Counter()
    )
    request = EmbeddingBatchRequest(custom_id="row-1", model="m", input_text="abcd")
    job = backend.submit([request])
    item = backend.retrieve(job)[0]
    assert item.embedding == [4.0]
    assert item.prompt_tokens == 42


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
