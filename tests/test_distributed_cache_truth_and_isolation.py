"""Regressions for cache-hit accounting truth and caller partition isolation."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from contextual_orchestrator import (
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    PriceEntry,
    TaskOrchestrator,
)
from contextual_orchestrator.orchestrator import ModelClient


class _MemoryCache:
    """Minimal process-local provider shaped like a shared response cache."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    def get(self, key: str) -> dict[str, object] | None:
        value = self.values.get(key)
        return copy.deepcopy(value) if value is not None else None

    def put(self, key: str, value: dict[str, object]) -> None:
        self.values[key] = copy.deepcopy(value)


class _CountingModelClient(ModelClient):
    """Count actual model executions while retaining the built-in mock transport."""

    def __init__(self) -> None:
        super().__init__(max_retries=0)
        self.calls = 0

    def chat(self, agent: ModelAgent, messages: list, temperature=None, top_p=None) -> str:  # type: ignore[override]
        self.calls += 1
        return super().chat(agent, messages, temperature=temperature, top_p=top_p)


def _orchestrator() -> tuple[TaskOrchestrator, _CountingModelClient]:
    """Build an orchestrator pinned to single-step routing for cache accounting.

    The model-triage gas and real-time judge are orthogonal to the cache layer
    under test, so both are disabled here: every counted call is one worker
    execution, which keeps ``calls`` an exact measure of provider executions.
    """
    client = _CountingModelClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "mock_worker",
                "mock-model",
                base_url="mock://worker",
                provider_name="mock",
                tags=("reasoning", "writing"),
            )
        ],
        client=client,
        cache_provider=_MemoryCache(),
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    return orchestrator, client


def test_cache_partition_prevents_cross_principal_reuse() -> None:
    """Identical prompts under different authenticated partitions must not collide."""
    orchestrator, client = _orchestrator()
    messages = [{"role": "user", "content": "same tenant-sensitive request"}]

    first_a = orchestrator.complete(messages, mode="route", cache_partition="principal-a")
    first_b = orchestrator.complete(messages, mode="route", cache_partition="principal-b")
    second_a = orchestrator.complete(messages, mode="route", cache_partition="principal-a")

    assert client.calls == 2
    assert first_a["cache_status"] == "miss"
    assert first_b["cache_status"] == "miss"
    assert second_a["cache_status"] == "hit"


def test_cache_hit_records_zero_provider_usage_instead_of_rebilling_inference() -> None:
    """A replayed answer is a cache request, not a second provider execution."""
    orchestrator, client = _orchestrator()
    config = InMemoryConfigStore()
    prices = PriceBook(config)
    prices.set_price(PriceEntry("mock", "mock-model", 1.0, 2.0))
    coordinator = CostRoutingCoordinator(
        orchestrator,
        config,
        price_book=prices,
    )
    messages = [{"role": "user", "content": "repeat this deterministic request"}]

    first = coordinator.complete(messages, mode="route", cache_partition="principal-a")
    second = coordinator.complete(messages, mode="route", cache_partition="principal-a")

    assert client.calls == 1
    assert first["cache_status"] == "miss"
    assert second["cache_status"] == "hit"
    assert second["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert second["cost"] == {"cost_amount": 0.0, "currency_code": "USD"}

    records = coordinator.ledger.records()
    assert len(records) == 2
    assert records[0]["request_channel"] == "sync"
    assert records[0]["provider_name"] == "mock"
    assert records[1]["request_channel"] == "cache"
    assert records[1]["provider_name"] == "cache"
    assert records[1]["prompt_tokens"] == 0
    assert records[1]["completion_tokens"] == 0
    assert records[1]["cost_amount"] == 0.0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
