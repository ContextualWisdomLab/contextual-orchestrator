"""Auto-optimizer — search orchestration configs for max quality at min cost.

Implements the Fugu quality-vs-cost tradeoff as an automated search: given candidate
configs and a caller-supplied quality signal, it measures real quality + cost per config
and recommends the best one (highest quality within a budget, or best quality-per-USD).
Quality is never fabricated — quality_fn is the caller's; here a deterministic mock.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import optimize_orchestration, _pareto_front  # noqa: E402


def _candidate(name: str, agent_id: str, price: float) -> dict:
    # Distinct agent id shows up in the mock answer, so quality_fn can differentiate configs.
    orchestrator = TaskOrchestrator(
        [ModelAgent(agent_id, "model-x", tags=("reasoning", "writing"))],
        price_per_million={"model-x": price},
    )
    return {"name": name, "orchestrator": orchestrator, "mode": "route"}


def _quality(task: dict, answer: str) -> float:
    # "strong" configs answer better; deterministic on the mock echo (which includes agent id).
    return 0.9 if "strong_worker" in answer else 0.6


TASKS = [{"prompt": "task one"}, {"prompt": "task two"}]


def test_optimizer_measures_quality_and_cost_per_config() -> None:
    candidates = [_candidate("cheap", "cheap_worker", price=1.0), _candidate("strong", "strong_worker", price=50.0)]
    report = optimize_orchestration(candidates, TASKS, _quality)

    by_name = {r["name"]: r for r in report["results"]}
    assert by_name["strong"]["quality"] == 0.9
    assert by_name["cheap"]["quality"] == 0.6
    assert by_name["strong"]["cost_usd"] > by_name["cheap"]["cost_usd"]  # pricier model costs more
    assert report["results"][0]["quality"] >= report["results"][-1]["quality"]  # sorted best-first


def test_pareto_front_keeps_nondominated() -> None:
    # cheap: low quality/low cost; strong: high quality/high cost -> neither dominates.
    candidates = [_candidate("cheap", "cheap_worker", 1.0), _candidate("strong", "strong_worker", 50.0)]
    report = optimize_orchestration(candidates, TASKS, _quality)
    assert set(report["pareto_front"]) == {"cheap", "strong"}


def test_recommend_prefers_quality_per_usd_without_budget() -> None:
    # cheap is far cheaper for 2/3 the quality -> better quality-per-USD.
    candidates = [_candidate("cheap", "cheap_worker", 1.0), _candidate("strong", "strong_worker", 50.0)]
    report = optimize_orchestration(candidates, TASKS, _quality)
    assert report["recommended"]["name"] == "cheap"
    assert report["recommended"]["reason"] == "best quality per USD"


def test_recommend_maximizes_quality_within_budget() -> None:
    candidates = [_candidate("cheap", "cheap_worker", 1.0), _candidate("strong", "strong_worker", 50.0)]
    # Budget generous enough for either -> pick the higher-quality "strong".
    report = optimize_orchestration(candidates, TASKS, _quality, cost_budget_usd=1.0)
    assert report["recommended"]["name"] == "strong"
    assert report["recommended"]["reason"] == "highest quality within cost budget"


def test_dominated_config_dropped_from_pareto() -> None:
    rows = [
        {"name": "a", "quality": 0.9, "cost_usd": 0.10},
        {"name": "b", "quality": 0.8, "cost_usd": 0.20},  # worse quality AND pricier -> dominated by a
        {"name": "c", "quality": 0.95, "cost_usd": 0.30},
    ]
    front = {r["name"] for r in _pareto_front(rows)}
    assert front == {"a", "c"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
