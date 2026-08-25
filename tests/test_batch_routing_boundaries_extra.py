"""Boundary coverage for the dependency-free local embedding fallback."""

from __future__ import annotations

from contextual_orchestrator.batch_routing import (
    EmbeddingBatchRequest,
    LocalEmbeddingBatchBackend,
)


def test_local_backend_without_token_counter_counts_word_units() -> None:
    """With no injected counter, token accounting falls back to word count."""
    backend = LocalEmbeddingBatchBackend()
    request = EmbeddingBatchRequest(
        custom_id=None,
        model="local-embedding-model",
        input_text="one two three   four\nfive",
    )
    job = backend.submit([request])

    assert job.request_count == 1
    results = backend.retrieve(job)
    assert len(results) == 1
    assert results[0].prompt_tokens == 5


def test_local_backend_injected_counter_still_takes_precedence() -> None:
    """An explicit counter overrides the word-count fallback."""

    class _Counter:
        def count_text(self, text: str, model: str) -> int:
            return 42

    backend = LocalEmbeddingBatchBackend(token_counter=_Counter())
    request = EmbeddingBatchRequest(
        custom_id="row-1",
        model="m",
        input_text="just four words here",
    )
    job = backend.submit([request])
    assert backend.retrieve(job)[0].prompt_tokens == 42


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
