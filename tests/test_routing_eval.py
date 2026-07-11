"""Measured routing eval — orchestration vs a single-worker baseline.

The moat of a router is that orchestration provably buys something over one model.
This harness MEASURES the tradeoff (latency cost vs structural coverage / a verifier
pass) rather than asserting quality. These check both arms are reported, the delta
math is right on a crafted case, and the result is deterministic on the mock path.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402


def _orch() -> TaskOrchestrator:
    return TaskOrchestrator([ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))])


def test_compare_returns_both_arms_and_structural_delta() -> None:
    report = _orch().compare_to_baseline(["analyze and verify this task"], mode="conduct")
    assert report["prompt_count"] == 1
    row = report["results"][0]
    assert row["orchestrated"]["mode"] == "conduct"
    assert row["orchestrated"]["steps"] == 4  # thinker + worker + verifier + synthesizer
    assert row["baseline"]["steps"] == 1  # single worker call
    assert row["structural_coverage_delta"] == 3
    assert isinstance(row["orchestrated"]["verified"], bool)
    assert "latency_ms" in row["orchestrated"] and "latency_ms" in row["baseline"]
    assert row["latency_overhead_ms"] == round(
        row["orchestrated"]["latency_ms"] - row["baseline"]["latency_ms"], 2
    )


def test_aggregate_math_is_correct() -> None:
    report = _orch().compare_to_baseline(["task one text", "task two text"], mode="conduct")
    aggregate = report["aggregate"]
    assert aggregate["orchestrated_avg_steps"] == 4.0
    assert aggregate["baseline_avg_steps"] == 1.0
    assert aggregate["avg_structural_coverage_delta"] == 3.0
    assert 0.0 <= aggregate["verified_share"] <= 1.0


def test_deterministic_on_mock_path() -> None:
    first = _orch().compare_to_baseline(["same task text"], mode="conduct")["results"][0]
    second = _orch().compare_to_baseline(["same task text"], mode="conduct")["results"][0]
    # Answer-derived fields are deterministic on mock (latency is not asserted).
    assert first["orchestrated"]["answer_length"] == second["orchestrated"]["answer_length"]
    assert first["baseline"]["answer_length"] == second["baseline"]["answer_length"]
    assert first["structural_coverage_delta"] == second["structural_coverage_delta"]


def test_quality_proxy_is_labeled_honestly() -> None:
    report = _orch().compare_to_baseline(["some task text"], mode="conduct")
    assert "NOT human-judged" in report["quality_proxy"]


def test_eval_does_not_persist_runs() -> None:
    # Read-only: measuring must not pollute the workflow-run store.
    orchestrator = _orch()
    orchestrator.compare_to_baseline(["measure me only"], mode="conduct")
    assert orchestrator._workflow_runs == {}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
