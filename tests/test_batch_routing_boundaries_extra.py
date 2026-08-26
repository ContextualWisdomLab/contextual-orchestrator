"""Boundary coverage for the dependency-free local embedding fallback."""

from __future__ import annotations

from contextual_orchestrator.batch_routing import (
    EmbeddingBatchRequest,
    LocalEmbeddingBatchBackend,
)
from contextual_orchestrator.token_counting import RustCl100kTokenCounter
from contextual_orchestrator.batch_routing import heuristic_embedding


def test_local_backend_requires_explicit_numeric_dependencies() -> None:
    """Production construction cannot invent vectors or token counts."""
    import pytest

    with pytest.raises(ValueError, match="explicit mock embedder"):
        LocalEmbeddingBatchBackend()


def test_local_backend_with_explicit_exact_counter() -> None:
    """The explicit local mock path uses the exact Rust counter."""
    backend = LocalEmbeddingBatchBackend(
        embedder=heuristic_embedding,
        token_counter=RustCl100kTokenCounter(),
    )
    request = EmbeddingBatchRequest(
        custom_id=None,
        model="local-embedding-model",
        input_text="one two three   four\nfive",
    )
    job = backend.submit([request])

    assert job.request_count == 1
    results = backend.retrieve(job)
    assert len(results) == 1
    assert results[0].prompt_tokens == RustCl100kTokenCounter().count_text(request.input_text)


def test_local_backend_injected_counter_still_takes_precedence() -> None:
    """An explicit counter overrides the word-count fallback."""

    class _Counter:
        def count_text(self, text: str, model: str) -> int:
            return 42

    backend = LocalEmbeddingBatchBackend(embedder=heuristic_embedding, token_counter=_Counter())
    request = EmbeddingBatchRequest(
        custom_id="row-1",
        model="m",
        input_text="just four words here",
    )
    job = backend.submit([request])
    assert backend.retrieve(job)[0].prompt_tokens == 42


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
