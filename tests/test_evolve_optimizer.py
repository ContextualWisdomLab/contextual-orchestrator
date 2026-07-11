"""Evolutionary optimizer — seeded mutation+selection over a config search space.

For spaces too large to enumerate. Each config is evaluated once and cached (real API
evaluations cost money), fitness maximizes measured quality then minimizes cost, and a
budget makes unaffordable configs rank below all affordable ones.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import evolve_orchestration, _space_size  # noqa: E402


# Config space: worker "tier" controls (deterministically) both quality and price.
TIERS = {
    "small_worker": {"price": 1.0, "quality": 0.5},
    "medium_worker": {"price": 10.0, "quality": 0.8},
    "large_worker": {"price": 60.0, "quality": 0.9},
}
SPACE = {"tier": list(TIERS), "mode": ["route"]}
TASKS = [{"prompt": "task one"}, {"prompt": "task two"}]

build_calls: list[str] = []


def _build(config: dict) -> TaskOrchestrator:
    build_calls.append(config["tier"])
    tier = TIERS[config["tier"]]
    return TaskOrchestrator(
        [ModelAgent(config["tier"], "model-x", tags=("reasoning", "writing"))],
        price_per_million={"model-x": tier["price"]},
    )


def _quality(task: dict, answer: str) -> float:
    for tier, spec in TIERS.items():
        if tier in answer:  # mock answer embeds the agent id
            return spec["quality"]
    return 0.0


def test_evolution_finds_best_quality_cheapest() -> None:
    build_calls.clear()
    report = evolve_orchestration(_build, SPACE, TASKS, _quality, generations=4, population=4, seed=3)
    best = report["recommended"]
    assert best["quality"] == 0.9  # found the top-quality tier
    assert report["results"][0]["config"]["tier"] == "large_worker"
    assert report["evaluations"] <= report["space_size"]  # never evaluates more than the space


def test_each_config_evaluated_once() -> None:
    build_calls.clear()
    report = evolve_orchestration(_build, SPACE, TASKS, _quality, generations=5, population=6, seed=1)
    # Space has only 3 configs; the cache must prevent re-paying for repeats across generations.
    assert report["space_size"] == 3
    assert report["evaluations"] <= 3
    assert len(build_calls) == report["evaluations"]  # one orchestrator build per unique config


def test_budget_reranks_to_affordable() -> None:
    # Budget below large_worker's cost -> best AFFORDABLE config wins instead.
    probe = evolve_orchestration(_build, SPACE, TASKS, _quality, generations=3, population=4, seed=3)
    large_cost = next(r["cost_usd"] for r in probe["results"] if r["config"]["tier"] == "large_worker")
    medium_cost = next(r["cost_usd"] for r in probe["results"] if r["config"]["tier"] == "medium_worker")
    budget = (large_cost + medium_cost) / 2  # affords medium, not large

    report = evolve_orchestration(_build, SPACE, TASKS, _quality, generations=3, population=4,
                                  cost_budget_usd=budget, seed=3)
    assert report["results"][0]["config"]["tier"] == "medium_worker"
    assert report["recommended"]["reason"] == "highest quality within cost budget"


def test_deterministic_for_same_seed() -> None:
    first = evolve_orchestration(_build, SPACE, TASKS, _quality, generations=3, population=4, seed=11)
    second = evolve_orchestration(_build, SPACE, TASKS, _quality, generations=3, population=4, seed=11)
    assert [r["name"] for r in first["results"]] == [r["name"] for r in second["results"]]
    assert first["history"] == second["history"]


def test_space_size_math() -> None:
    assert _space_size({"a": [1, 2, 3], "b": [1, 2]}) == 6
    assert _space_size({}) == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
