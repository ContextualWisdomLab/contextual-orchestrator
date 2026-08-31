"""Batch-powered optimizer — route-mode evaluations ride the ~50% Batch lane.

batch_route routes many prompts through the provider Batch API and persists them as
normal route runs (usage kept), so spend/observability are unchanged. optimize/evolve
gain use_batch: route configs evaluate via one batch, conduct stays serial.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextual_orchestrator.orchestrator as orchestrator_module
from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient, optimize_orchestration


class _CountingClient(ModelClient):
    """Counts chat vs batch calls; batch reports usage so spend sees reported tokens."""

    def __init__(self) -> None:
        super().__init__()
        self.chat_calls = 0
        self.batch_calls = 0

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.chat_calls += 1
        return super().chat(agent, messages, temperature)

    def batch_chat(self, agent: ModelAgent, requests: dict, temperature: float = 0.2,  # type: ignore[override]
                   poll_interval: float = 5.0, poll_timeout: float = 3600.0) -> dict:
        self.batch_calls += 1
        return {
            custom_id: {"content": self._mock(agent, messages),
                        "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10}}
            for custom_id, messages in requests.items()
        }


class _InvalidBatchClient(_CountingClient):
    """Produces one malformed batch result to verify fail-closed persistence."""

    def __init__(self, kind: str) -> None:
        super().__init__()
        self.kind = kind

    def batch_chat(self, agent: ModelAgent, requests: dict, temperature: float = 0.2,  # type: ignore[override]
                   poll_interval: float = 5.0, poll_timeout: float = 3600.0) -> dict:
        results = super().batch_chat(agent, requests, temperature, poll_interval, poll_timeout)
        if self.kind == "missing":
            results.pop("task_1")
        else:
            results["task_1"]["content"] = None
        return results


def _orch(client: ModelClient | None = None) -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing"))],
        client=client,
        price_per_million={"model-x": 10.0},
    )


TASKS = [{"prompt": "task one"}, {"prompt": "task two"}, {"prompt": "task three"}]


def test_batch_route_persists_runs_with_usage() -> None:
    client = _CountingClient()
    orchestrator = _orch(client)
    records = orchestrator.batch_route([t["prompt"] for t in TASKS])

    assert len(records) == 3
    assert client.batch_calls == 1 and client.chat_calls == 0  # one batch, zero serial calls
    assert len(orchestrator._workflow_runs) == 3  # persisted as normal route runs
    spend = orchestrator.spend_analytics()
    assert spend["totals"]["run_count"] == 3
    row = spend["by_model"][0]
    assert row["usage_source"] == "reported"  # batch usage threaded into spend
    assert row["output_tokens"] == 18  # 3 x 6 reported completion tokens


def test_optimizer_use_batch_routes_via_batch_and_matches_serial() -> None:
    batch_client = _CountingClient()
    serial_client = _CountingClient()
    report_batch = optimize_orchestration(
        [{"name": "route_cfg", "orchestrator": _orch(batch_client), "mode": "route"}],
        TASKS, lambda task, answer: 1.0 if "general_agent" in answer else 0.0, use_batch=True)
    report_serial = optimize_orchestration(
        [{"name": "route_cfg", "orchestrator": _orch(serial_client), "mode": "route"}],
        TASKS, lambda task, answer: 1.0 if "general_agent" in answer else 0.0, use_batch=False)

    assert batch_client.batch_calls == 1 and batch_client.chat_calls == 0
    assert serial_client.batch_calls == 0 and serial_client.chat_calls == 3
    # Same mock answers -> identical quality either lane.
    assert report_batch["results"][0]["quality"] == report_serial["results"][0]["quality"] == 1.0


def test_conduct_config_stays_serial_even_with_use_batch() -> None:
    client = _CountingClient()
    with patch.object(orchestrator_module, "_resolve_fast_mlsirm_components", return_value=None):
        optimize_orchestration(
            [{"name": "conduct_cfg", "orchestrator": _orch(client), "mode": "conduct"}],
            TASKS[:1], lambda task, answer: 1.0, use_batch=True)
    assert client.batch_calls == 0  # multi-step cannot batch
    assert client.chat_calls == 4  # thinker/worker/verifier/synthesizer; missing fast-mlsirm fails closed


def test_mock_default_batch_route_works_without_usage() -> None:
    orchestrator = _orch()  # plain ModelClient: mock batch_chat is sync, usage None
    records = orchestrator.batch_route(["hello there"])
    assert records[0]["answer"].startswith("[general_agent:")
    assert orchestrator.spend_analytics()["by_model"][0]["usage_source"] == "estimated"


@pytest.mark.parametrize("kind", ["missing", "content"])
def test_batch_route_rejects_incomplete_or_empty_provider_results(kind: str) -> None:
    orchestrator = _orch(_InvalidBatchClient(kind))

    with pytest.raises(RuntimeError, match="batch provider"):
        orchestrator.batch_route([t["prompt"] for t in TASKS])
    assert orchestrator._workflow_runs == {}


class _ScriptedFastJudge:
    """Deterministic fast-mlsirm stand-in: rejects any answer matching a marker."""

    def __init__(self, adapter, *, mode: str, accept_threshold: float) -> None:
        del adapter, mode, accept_threshold

    def judge(self, *, task: str, answer: str, criteria: tuple) -> object:
        del task, criteria
        accepted = "task two" not in answer
        return SimpleNamespace(
            accepted=accepted,
            rationale="scripted reject" if not accepted else "scripted accept",
            criterion_scores={"evidence_quality": 1.0, "risk_signal": 1.0},
            usage=None,
            orchestration_mode="route",
            to_irt_row=lambda *, item_type: (int(accepted), int(accepted)),
        )


def _scripted_fast_components() -> orchestrator_module.FastMLSIRMJudgeComponents:
    return orchestrator_module.FastMLSIRMJudgeComponents(
        judge_cls=_ScriptedFastJudge,
        criterion_cls=lambda **kwargs: kwargs,
        format_error=ValueError,
    )


def test_batch_route_records_real_judge_rejection() -> None:
    """realtime_judge=True (the default) must feed each batched answer through the
    same genuine fast-mlsirm judge route_once uses -- not a hardcoded pass. This
    fails against the pre-fix hardcoded ``{"accepted": True, ...}`` literal.
    """
    client = _CountingClient()
    orchestrator = _orch(client)
    assert orchestrator.policy.realtime_judge is True  # exercising the default

    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        records = orchestrator.batch_route([t["prompt"] for t in TASKS])

    by_prompt = {record["prompt_text"]: record for record in records}
    rejected = by_prompt["task two"]
    accepted = by_prompt["task one"]

    assert rejected["verification"]["accepted"] is False
    assert rejected["verification"]["reason"] == "scripted reject"
    assert rejected["verification"]["verifier_output"] == rejected["answer"]
    assert rejected["verification"]["verifier_output"] != ""

    assert accepted["verification"]["accepted"] is True
    assert accepted["verification"]["reason"] == "scripted accept"
    assert accepted["verification"]["verifier_output"] == accepted["answer"]


def test_batch_route_realtime_judge_disabled_uses_reviewed_fallback() -> None:
    """With realtime_judge explicitly off, batch_route must fall back to the same
    reviewed shape _realtime_route_judge already produces for route_once -- a real,
    non-empty verifier_output echoing the answer, not the old batch-only fabrication.
    """
    client = _CountingClient()
    orchestrator = _orch(client)
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)

    records = orchestrator.batch_route([t["prompt"] for t in TASKS])

    for record in records:
        verification = record["verification"]
        assert verification == {
            "accepted": True,
            "reason": "single route path",
            "verifier_output": record["answer"],
            "judge": "model",
        }
        assert verification["verifier_output"] != ""


def test_batch_route_does_not_corrupt_sync_route_quality_latency() -> None:
    """A shared Batch API call's total elapsed time must never become one
    answer's latency sample in the synchronous-route quality EWMA -- doing
    so would let one slow/large batch demote a fast model in later
    route_once ranking (Devin review, PR #961). The judge's accept/reject
    signal is still recorded as stability evidence.
    """
    client = _CountingClient()
    orchestrator = _orch(client)

    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        records = orchestrator.batch_route(["task one", "task three"])

    assert len(records) == 2
    assert all(record["verification"]["accepted"] is True for record in records)
    report = orchestrator._quality_router.member_report("general_agent")
    assert report["ewma_latency_seconds"] is None
    assert orchestrator._quality_router.member_observation_count("general_agent") == 2
    # The shared batch timing itself stays honestly visible on each trace row.
    assert all(record["trace"][0]["latency_ms"] is not None for record in records)


def test_batch_route_rechecks_budget_before_each_judge_call() -> None:
    """batch_route's one-time budget check at entry does not cover the N
    additional judge provider calls the loop makes afterward. A large batch
    must not silently blow through the spend cap while every judge call
    keeps running unchecked (Devin review, PR #961).
    """
    client = _CountingClient()
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing"))],
        client=client,
        price_per_million={"model-x": 10.0},
        budget_max_output_tokens=6,  # exactly one item's reported completion_tokens
    )

    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        with pytest.raises(orchestrator_module.BudgetExceededError):
            orchestrator.batch_route(["task one", "task three"])

    # The first item's judge call and persistence completed before the
    # second item's pre-judge budget check stopped the batch -- proof the
    # loop re-checks per item rather than only once before it starts.
    assert len(orchestrator._workflow_runs) == 1


def test_batch_chat_rejects_incomplete_local_result_set() -> None:
    client = ModelClient()
    agent = ModelAgent("local_agent", "model-x", base_url="local://127.0.0.1:1")
    requests = {
        "task_0": [{"role": "user", "content": "one"}],
        "task_1": [{"role": "user", "content": "two"}],
    }
    with patch.object(client, "_local_batch_chat", return_value={
        "task_0": {"content": "ok", "usage": None},
    }), pytest.raises(RuntimeError, match="incomplete or unexpected"):
        client.batch_chat(agent, requests)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
