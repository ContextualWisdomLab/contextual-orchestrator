"""Regression contracts for evidence-only sync/batch and embedding routing."""

from __future__ import annotations

import pytest

from contextual_orchestrator.batch_routing import (
    EmbeddingBatchRequest,
    LocalEmbeddingBatchBackend,
    RoutingHints,
    RoutingPolicy,
    cheapest_upstream,
)
from contextual_orchestrator.kv_config import InMemoryConfigStore


class _ExactEmbeddingCounter:
    """Tiny exact-token counter used only to isolate the embedding decision seam."""

    def count_text(self, text: str, model: str) -> int:
        del model
        return len(text.encode("utf-8"))


class _StaticPriceBook:
    """Price-book double whose costs are exact and independent of request shape."""

    def compute_cost(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> tuple[float, str, bool]:
        del provider, model
        return float(prompt_tokens + completion_tokens), "USD", True


def test_implicit_hints_and_token_threshold_cannot_select_batch() -> None:
    """Only an explicit channel request may change sync into batch."""
    config = InMemoryConfigStore()
    config.set("routing", "batch_min_tokens", 1)
    config.set("routing", "interactive_forces_sync", False)
    policy = RoutingPolicy(config)

    assert policy.decide(RoutingHints(latency_tolerant=True), prompt_tokens=50_000).channel == "sync"
    assert policy.decide(RoutingHints(priority="bulk"), prompt_tokens=50_000).channel == "sync"
    assert policy.decide(RoutingHints(), prompt_tokens=50_000).channel == "sync"


def test_explicit_batch_channel_remains_subject_to_operator_enablement() -> None:
    """Explicit caller intent is authoritative unless batch execution is disabled."""
    enabled = RoutingPolicy(InMemoryConfigStore())
    assert enabled.decide(RoutingHints(channel="batch"), prompt_tokens=None).channel == "batch"

    disabled_config = InMemoryConfigStore()
    disabled_config.set("routing", "batch_enabled", False)
    disabled = RoutingPolicy(disabled_config)
    assert disabled.decide(RoutingHints(channel="batch"), prompt_tokens=None).channel == "sync"


def test_local_embedding_backend_fails_closed_without_an_explicit_embedder() -> None:
    """Standalone mode must never fabricate semantic vectors from a hash digest."""
    backend = LocalEmbeddingBatchBackend(token_counter=_ExactEmbeddingCounter())
    request = EmbeddingBatchRequest(input_text="semantic evidence", model="embedding_model")

    with pytest.raises(RuntimeError, match="explicit embedding implementation"):
        backend.submit([request])


def test_local_embedding_backend_uses_an_explicit_injected_embedder() -> None:
    """A caller-supplied exact implementation remains a valid local test/backend seam."""
    backend = LocalEmbeddingBatchBackend(
        embedder=lambda text: [float(len(text))],
        token_counter=_ExactEmbeddingCounter(),
    )
    request = EmbeddingBatchRequest(input_text="abc", model="embedding_model")

    job = backend.submit([request])
    assert backend.retrieve(job)[0].embedding == [3.0]


def test_cost_selector_requires_an_explicit_request_shape() -> None:
    """Cost routing must not invent representative prompt/completion token counts."""
    candidates = [{"provider": "provider_one", "model": "model_one"}]

    with pytest.raises(TypeError):
        cheapest_upstream(candidates, _StaticPriceBook())
