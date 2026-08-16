"""Min-cost / max-performance selection: one worker, no next-agent walk.

Unique slice vs PR #642, which still implements 429 → next capability-matched
agent failover. Transient retry on the chosen worker is allowed; sequential
agent hopping is not.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, PriceBook, PriceEntry, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.kv_config import InMemoryConfigStore  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.priced_selection import (  # noqa: E402
    billed_selection_cost,
    select_min_cost_max_performance,
)


class _RecordingClient(ModelClient):
    def __init__(self, down_id: str | None = None) -> None:
        super().__init__(retry_backoff=0.0)
        self.down_id = down_id
        self.calls: list[str] = []

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.calls.append(agent.id)
        if agent.id == self.down_id:
            raise RuntimeError(f"{agent.id} unavailable")
        return f"[{agent.id}] answer"


def _priced_orchestrator(client: ModelClient | None = None) -> TaskOrchestrator:
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry("cheap_co", "cheap-model", prompt_price_per_1k=0.01, completion_price_per_1k=0.01)
    )
    price_book.set_price(
        PriceEntry("pricey_co", "pricey-model", prompt_price_per_1k=5.0, completion_price_per_1k=10.0)
    )
    agents = [
        ModelAgent(
            "pricey_worker",
            "pricey-model",
            tags=("reasoning", "writing", "coding"),
            priority=9,
            provider_name="pricey_co",
        ),
        ModelAgent(
            "cheap_worker",
            "cheap-model",
            tags=("reasoning", "writing", "coding"),
            priority=1,
            provider_name="cheap_co",
        ),
    ]
    return TaskOrchestrator(agents, client=client or _RecordingClient(), price_book=price_book)


def test_select_prefers_min_cost_over_hardcoded_priority_rank() -> None:
    orchestrator = _priced_orchestrator()
    selected = orchestrator._select_agent("route this", "worker")
    assert selected.id == "cheap_worker"


def test_select_max_performance_when_billed_cost_ties() -> None:
    agents = [
        ModelAgent("low_skill", "same-model", tags=("writing",), priority=0, provider_name="acme"),
        ModelAgent("high_skill", "same-model", tags=("reasoning", "coding", "writing"), priority=2, provider_name="acme"),
    ]

    def capability(agent: ModelAgent) -> tuple:
        return (len(agent.tags) + agent.priority, agent.id)

    chosen = select_min_cost_max_performance(
        agents,
        role="worker",
        capability_score=capability,
        billed_cost=lambda _agent: 0.0,
        is_circuit_open=lambda _agent_id: False,
    )
    assert chosen.id == "high_skill"


def test_invoke_does_not_walk_next_agent_list() -> None:
    client = _RecordingClient(down_id="cheap_worker")
    orchestrator = _priced_orchestrator(client=client)
    raised = False
    try:
        orchestrator.route_once([{"role": "user", "content": "route this"}])
    except RuntimeError as exc:
        raised = True
        assert "cheap_worker" in str(exc)
        assert "candidate agents failed" not in str(exc)
    assert raised
    assert client.calls == ["cheap_worker"]


def test_failover_candidates_is_not_a_next_agent_walk() -> None:
    orchestrator = _priced_orchestrator()
    primary = orchestrator._select_agent("route this", "worker")
    candidates = orchestrator._failover_candidates(primary, "route this", "worker")
    assert [agent.id for agent in candidates] == [primary.id]


def test_circuit_open_is_excluded_from_next_selection_not_hopped() -> None:
    client = _RecordingClient(down_id="cheap_worker")
    orchestrator = _priced_orchestrator(client=client)
    orchestrator.circuit_failure_threshold = 1
    try:
        orchestrator.route_once([{"role": "user", "content": "route this"}])
    except RuntimeError:
        pass
    assert orchestrator._circuit_open("cheap_worker") is True
    selected = orchestrator._select_agent("route this", "worker")
    assert selected.id == "pricey_worker"
    result = orchestrator.route_once([{"role": "user", "content": "route this"}])
    assert result["answer"] == "[pricey_worker] answer"
    assert "failover_from" not in result["trace"][0]
    assert client.calls == ["cheap_worker", "pricey_worker"]


def test_billed_cost_ignores_original_list_price() -> None:
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry(
            "promo_co",
            "promo-model",
            prompt_price_per_1k=0.0,
            completion_price_per_1k=0.0,
            original_list_price={"prompt_price_per_1k": 2.0, "completion_price_per_1k": 4.0},
        )
    )
    agent = ModelAgent("promo_worker", "promo-model", provider_name="promo_co")
    cost = billed_selection_cost(
        agent, price_book=price_book, price_per_million={}, any_explicit_price=True
    )
    assert cost == 0.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
