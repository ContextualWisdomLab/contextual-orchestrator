"""Boundary coverage for the dependency-free local embedding fallback."""

from __future__ import annotations

import pytest

from contextual_orchestrator.batch_routing import (
    EmbeddingBatchRequest,
    LocalEmbeddingBatchBackend,
)


def test_local_backend_without_token_counter_fails_closed() -> None:
    """Missing authoritative accounting must not become a word-count estimate."""
    backend = LocalEmbeddingBatchBackend()
    request = EmbeddingBatchRequest(
        custom_id=None,
        model="local-embedding-model",
        input_text="one two three   four\nfive",
    )
    with pytest.raises(RuntimeError, match="authoritative embedding tokenizer"):
        backend.submit([request])


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
