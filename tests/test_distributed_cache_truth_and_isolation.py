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
    default_role_effort_catalog,
)
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.reasoning_effort_profile import (
    EffortProfileError,
    snapshot_role_effort_catalog,
)


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


@pytest.mark.parametrize("cache_kind", ["local", "shared"])
def test_policy_change_requires_new_judgment_before_answer_reuse(monkeypatch, cache_kind):
    """Enabling judging must not return a previously unjudged cached answer."""
    cache_options = {"cache_ttl": 60} if cache_kind == "local" else {"cache_provider": _MemoryCache()}
    gateway = TaskOrchestrator([ModelAgent("policy_worker", "mock")], **cache_options)
    gateway.policy = replace(gateway.policy, realtime_judge=False)
    judge_calls = []

    def judge_reply(task_text, verification, **_request_options):
        """Count the real judgment boundary without contacting an external provider."""
        judge_calls.append(task_text)
        return {**verification, "accepted": True, "reason": "unit judge executed", "judge": "model"}

    monkeypatch.setattr(gateway, "_model_judge_verification", judge_reply)
    messages = [{"role": "user", "content": "cache policy unit fixture"}]
    try:
        first_result = gateway.run(messages, mode="route")
        gateway.policy = replace(gateway.policy, realtime_judge=True)
        changed_result = gateway.run(messages, mode="route")
        gateway.policy = replace(gateway.policy)
        repeated_result = gateway.run(messages, mode="route")
        assert judge_calls == ["cache policy unit fixture"]
        assert [first_result["cache_status"], changed_result["cache_status"], repeated_result["cache_status"]] == [
            "miss", "miss", "hit"
        ]
        assert changed_result["verification"]["reason"] == "unit judge executed"
        assert repeated_result["policy_snapshot"] == changed_result["policy_snapshot"]
    finally:
        gateway.close()


@pytest.mark.parametrize("cache_kind", ["local", "shared"])
def test_effort_catalog_changes_do_not_reuse_prior_answers(monkeypatch, cache_kind):
    """Separate declared decode settings in both cache paths; reuse equal content."""
    catalog = default_role_effort_catalog()
    cache_options = {"cache_ttl": 60} if cache_kind == "local" else {"cache_provider": _MemoryCache()}
    orchestrator = TaskOrchestrator(
        [ModelAgent("audit_worker", "mock", tags=("reasoning",))],
        role_effort_catalog=catalog,
        **cache_options,
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    worker_efforts = []

    def chat(agent, messages, *, effort_profile):
        """Expose the profile received by the worker double without external calls."""
        worker_efforts.append(effort_profile.reasoning_effort)
        return "answer-" + effort_profile.reasoning_effort

    monkeypatch.setattr(orchestrator.client, "chat", chat)
    messages = [{"role": "user", "content": "same declared task"}]
    try:
        first = orchestrator.run(messages, mode="route")
        catalog["worker"] = replace(catalog["worker"], reasoning_effort="high")
        changed = orchestrator.run(messages, mode="route")
        orchestrator.role_effort_catalog = dict(catalog)
        repeated = orchestrator.run(messages, mode="route")

        assert worker_efforts == ["medium", "high"]
        assert [first["answer"], changed["answer"], repeated["answer"]] == [
            "answer-medium", "answer-high", "answer-high"
        ]
        assert [first["cache_status"], changed["cache_status"], repeated["cache_status"]] == [
            "miss", "miss", "hit"
        ]
        assert changed["reasoning_effort_snapshot"] == repeated["reasoning_effort_snapshot"]
        assert changed["reasoning_effort_snapshot"]["snapshot_hash"] == (
            snapshot_role_effort_catalog(catalog).snapshot_hash
        )
    finally:
        orchestrator.close()


def test_invalid_effort_catalog_cannot_hit_cache_or_execute_worker(monkeypatch):
    """A malformed catalog is not a cache outage and must fail before execution."""
    catalog = default_role_effort_catalog()
    orchestrator = TaskOrchestrator(
        [ModelAgent("audit_worker", "mock", tags=("reasoning",))],
        role_effort_catalog=catalog,
        cache_ttl=60,
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    worker_calls = []

    def chat(agent, messages, **kwargs):
        """Count worker calls on both warm-cache and invalid-catalog paths."""
        worker_calls.append(agent.id)
        return "answer"

    monkeypatch.setattr(orchestrator.client, "chat", chat)
    messages = [{"role": "user", "content": "same declared task"}]
    try:
        orchestrator.complete(messages, mode="route")
        catalog.pop("judge")
        with pytest.raises(EffortProfileError, match="catalog must bind exactly"):
            orchestrator.complete(messages, mode="route")
        assert worker_calls == ["audit_worker"]
    finally:
        orchestrator.close()


def test_run_preserves_completion_snapshot_after_settings_change(monkeypatch):
    """Persist the completion's detached metadata, not later operator settings."""
    catalog = default_role_effort_catalog()
    orchestrator = TaskOrchestrator(
        [ModelAgent("audit_worker", "mock", tags=("reasoning",))],
        role_effort_catalog=catalog,
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    original_complete = orchestrator.complete
    completed = []

    def complete_then_change(*args, **kwargs):
        """Change settings at the boundary after a genuine local completion returns."""
        result = original_complete(*args, **kwargs)
        completed.append(result)
        catalog["worker"] = replace(catalog["worker"], reasoning_effort="high")
        return result

    monkeypatch.setattr(orchestrator, "complete", complete_then_change)
    try:
        record = orchestrator.run([{"role": "user", "content": "preserve settings"}], mode="route")
        expected = copy.deepcopy(completed[0]["reasoning_effort_snapshot"])
        assert record["reasoning_effort_snapshot"] == expected
        completed[0]["reasoning_effort_snapshot"]["role_profiles"]["worker"]["reasoning_effort"] = "low"
        assert record["reasoning_effort_snapshot"] == expected
    finally:
        orchestrator.close()


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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
