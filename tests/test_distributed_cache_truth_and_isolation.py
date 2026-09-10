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
from contextual_orchestrator.orchestrator import (
    ModelClient,
    _REQUEST_ZDR_ONLY,
    _request_endpoint_partition,
)
from contextual_orchestrator.response_cache import build_response_cache_key


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
    assert second["cost"] == {
        "cost_amount": 0.0,
        "currency_code": "USD",
        "price_known": True,
        "measurement_status": "measured",
    }

    records = coordinator.ledger.records()
    assert len(records) == 2
    assert records[0]["request_channel"] == "sync"
    assert records[0]["provider_name"] == "mock"
    assert records[1]["request_channel"] == "cache"
    assert records[1]["provider_name"] == "cache"
    assert records[1]["prompt_tokens"] == 0
    assert records[1]["completion_tokens"] == 0
    assert records[1]["cost_amount"] == 0.0


def test_orchestrator_free_auto_rejects_legacy_conduct_cache_entries() -> None:
    """A pre-change FREE_MODEL auto cache entry must not outlive the route contract.

    The hand-built legacy key below intentionally matches every current
    ``_cache_key`` input (including the unrelated endpoint-partition fold)
    except ``resolved_mode``, so a cache miss here isolates and proves the
    ``resolved_mode`` differentiation this test targets rather than an
    incidental partition mismatch.
    """
    client = _CountingModelClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "mock_free_worker",
                "mock-free-model",
                base_url="mock://worker",
                provider_name="mock",
                tags=("reasoning", "writing", "cost:free"),
            )
        ],
        client=client,
        cache_provider=_MemoryCache(),
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator._triage_fn = lambda _text: True
    messages = [{"role": "user", "content": "review and verify this legacy cache contract"}]
    legacy_key = build_response_cache_key(
        messages,
        "auto",
        model=TaskOrchestrator.FREE_MODEL,
        parameters={
            "temperature": getattr(orchestrator.client, "default_temperature", None),
            "top_p": getattr(orchestrator.client, "default_top_p", None),
            "presence_penalty": getattr(orchestrator.client, "default_presence_penalty", None),
            "frequency_penalty": getattr(orchestrator.client, "default_frequency_penalty", None),
            "max_output_tokens": getattr(orchestrator.client, "max_output_tokens", None),
            "zdr_only": _REQUEST_ZDR_ONLY.get(),
        },
        partition=_request_endpoint_partition(),
    )
    assert isinstance(orchestrator._cache_provider, _MemoryCache)
    orchestrator._cache_provider.put(
        legacy_key,
        {
            "mode": "conduct",
            "answer": "stale conduct answer",
            "trace": [{"role": "thinker"}],
        },
    )

    result = orchestrator.complete(messages, mode="auto", model_name=TaskOrchestrator.FREE_MODEL)

    assert client.calls == 1
    assert result["cache_status"] == "miss"
    assert result["mode"] == "route"
    assert result["answer"] != "stale conduct answer"


def test_auto_default_model_cache_hit_never_invokes_live_triage() -> None:
    """A warm cache entry for the default/auto path must not pay for triage.

    Regression: folding ``resolved_mode`` into the cache key made ``complete()``
    call ``would_route()`` -- and therefore the live, model-backed triage call
    -- unconditionally *before* the cache lookup. For ``mode="auto"`` against
    the gateway default model, that decision genuinely needs a real provider
    call whenever the process-local triage cache is cold (a fresh replica, an
    evicted entry), even when the distributed response cache already holds the
    answer. A cache hit must short-circuit before that call ever happens.
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
    triage_calls = 0

    def _counting_triage(_text: str) -> bool:
        nonlocal triage_calls
        triage_calls += 1
        return False

    orchestrator._triage_fn = _counting_triage
    messages = [{"role": "user", "content": "warm-cache default auto request"}]
    key = orchestrator._cache_key(messages, "auto", TaskOrchestrator.GATEWAY_DEFAULT_MODEL, None)
    assert isinstance(orchestrator._cache_provider, _MemoryCache)
    orchestrator._cache_provider.put(
        key,
        {"mode": "route", "answer": "warm answer", "trace": [{"role": "worker"}]},
    )

    result = orchestrator.complete(messages, mode="auto")

    assert result["cache_status"] == "hit"
    assert result["answer"] == "warm answer"
    assert triage_calls == 0
    assert client.calls == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
