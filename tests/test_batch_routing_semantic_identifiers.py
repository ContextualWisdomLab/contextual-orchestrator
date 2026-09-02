"""Regression coverage for semantic identifiers in batch-routing internals."""

import inspect

from contextual_orchestrator.batch_routing import (
    PgLlmBatchBackend,
    PgLlmBatchEmbeddingBackend,
)


def test_pg_batch_backends_expose_semantic_coroutine_runner_names() -> None:
    """Keep organization-owned async bridges specific to the batch context."""
    for batch_backend_type in (PgLlmBatchBackend, PgLlmBatchEmbeddingBackend):
        assert hasattr(batch_backend_type, "_run_batch_coroutine")
        assert not hasattr(batch_backend_type, "_run")
        coroutine_runner = getattr(batch_backend_type, "_run_batch_coroutine")
        assert list(inspect.signature(coroutine_runner).parameters) == ["batch_coroutine"]
