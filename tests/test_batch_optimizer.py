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
    # This test isolates the worker batch's no-usage fallback.  The optional
    # fast-mlsirm extra is installed in the full CI environment and would add
    # a separate, reported judge call, legitimately making the aggregate
    # usage source mixed instead of estimated.
    with patch.object(orchestrator_module, "_resolve_fast_mlsirm_components", return_value=None):
        records = orchestrator.batch_route(["hello there"])
    assert records[0]["answer"].startswith("[general_agent:")
    assert orchestrator.spend_analytics()["by_model"][0]["usage_source"] == "estimated"


@pytest.mark.parametrize("kind", ["missing", "content"])
def test_batch_route_rejects_incomplete_or_empty_provider_results(kind: str) -> None:
    """The group as a whole is rejected, but its other, independently-valid
    items' real spend must survive (Devin review on #961): a fully-invalid
    or all-or-nothing loss defeats the point of persisting a group's results
    as soon as it validates, for the exact same reason an unrelated later
    group's failure must not erase an earlier group's already-completed one.
    """
    orchestrator = _orch(_InvalidBatchClient(kind))

    with pytest.raises(RuntimeError, match="batch provider"):
        orchestrator.batch_route([t["prompt"] for t in TASKS])

    # task_1 ("task two") is the one dropped/malformed item; task_0 and
    # task_2 ("task one"/"task three") are still salvaged as pending.
    assert len(orchestrator._workflow_runs) == 2
    prompts = {run["prompt_text"] for run in orchestrator._workflow_runs.values()}
    assert prompts == {"task one", "task three"}
    assert all(
        run["pending_verification"] is True
        for run in orchestrator._workflow_runs.values()
    )
    assert orchestrator.budget_status()["spent_output_tokens"] == 12  # 2 x 6


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

    # The already-completed batch worker spend is real and already
    # persisted -- both rows land in the store (their spend already
    # reflected in the budget meter) before the judge loop's checkpoint
    # even runs, so the exhausted cap does not vanish along with the raise;
    # the first per-item checkpoint just stops before any judge call.
    assert len(orchestrator._workflow_runs) == 2
    assert orchestrator.budget_status()["spent_output_tokens"] == 12
    assert not any(
        orchestrator._is_trace_complete(run) for run in orchestrator._workflow_runs.values()
    )


def test_batch_route_budget_counts_only_the_current_uncommitted_worker() -> None:
    client = _CountingClient()

    def varied_batch(_agent, requests, **_kwargs):
        completion_tokens = {"task_0": 6, "task_1": 1}
        return {
            custom_id: {
                "content": custom_id,
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": completion_tokens[custom_id],
                    "total_tokens": 1 + completion_tokens[custom_id],
                },
            }
            for custom_id in requests
        }

    client.batch_chat = varied_batch  # type: ignore[method-assign]
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing"))],
        client=client,
        price_per_million={"model-x": 10.0},
        budget_max_output_tokens=10,
    )

    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        records = orchestrator.batch_route(["task one", "task three"])

    assert len(records) == 2
    # 7 real worker tokens (6 + 1) plus an honest estimated-token fallback
    # for each of the two judge calls, whose scripted response carries no
    # usage: estimate_tokens("task_0") == estimate_tokens("task_1") == 2
    # (Devin review on #961: a completed-but-unmeasured judge call must
    # still count toward the budget meter, not silently contribute 0).
    assert orchestrator.budget_status()["spent_output_tokens"] == 11


def test_batch_route_blocks_first_judge_call_when_aggregate_batch_spend_exceeds_cap() -> None:
    """No row's own reported spend exceeds the cap, but the batch's total does.

    Every worker request in a batch completes together, before any judge
    call starts -- so by the time the first per-item checkpoint runs, every
    row's spend has already happened even though only the current row is
    persisted. A checkpoint that only looked at the current row (Devin
    review, PR #961) would let the first judge call start anyway, hiding
    the rest of the batch's already-incurred spend until later iterations
    -- or never, if the loop stops early. The checkpoint must see the true
    unpersisted remainder (this row through the end of the batch) so a
    batch whose aggregate spend already exceeds the cap blocks its very
    first judge call.
    """
    client = _CountingClient()  # every item reports completion_tokens=6
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing"))],
        client=client,
        price_per_million={"model-x": 10.0},
        budget_max_output_tokens=10,  # below the two-item aggregate (12), above one item (6)
    )

    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        with pytest.raises(orchestrator_module.BudgetExceededError):
            orchestrator.batch_route(["task one", "task three"])

    # The aggregate checkpoint must reject before the first judge call, but
    # the batch's real worker spend is already persisted -- and so already
    # counted -- rather than lost by the raise.
    assert len(orchestrator._workflow_runs) == 2
    assert orchestrator.budget_status()["spent_output_tokens"] == 12
    assert not any(
        orchestrator._is_trace_complete(run) for run in orchestrator._workflow_runs.values()
    )


def test_batch_route_retry_after_budget_exceeded_cannot_incur_untracked_spend() -> None:
    """A completed batch's spend must stay counted so a retry fails closed.

    Devin review (PR #961): if the aggregate checkpoint raised without
    persisting the batch's already-incurred worker spend, the budget meter
    would stay unchanged and a caller retrying the same over-budget batch
    could keep incurring real, uncounted provider spend indefinitely.
    """
    client = _CountingClient()  # every item reports completion_tokens=6
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing"))],
        client=client,
        price_per_million={"model-x": 10.0},
        budget_max_output_tokens=10,
    )

    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        with pytest.raises(orchestrator_module.BudgetExceededError):
            orchestrator.batch_route(["task one", "task three"])
        assert orchestrator.budget_status()["exceeded"] is True

        # A retry must fail closed at the ordinary entry check -- the first
        # attempt's real spend is already counted, so this second call
        # cannot execute another provider batch call at all.
        batch_calls_before_retry = client.batch_calls
        with pytest.raises(orchestrator_module.BudgetExceededError):
            orchestrator.batch_route(["task one", "task three"])
        assert client.batch_calls == batch_calls_before_retry


def test_batch_route_survives_restart_after_budget_exceeded(tmp_path) -> None:
    """A restart must not erase a failed batch's already-incurred spend.

    Devin review (PR #961): persisting pending worker rows only to the
    in-memory budget meter kept a process restart before judging from
    reloading any of a failed batch's spend, letting the same over-budget
    batch be retried with a full budget again after every restart. Pending
    rows are now saved to the durable ``--state-db`` store too, the same as
    a judged run already was -- but a reloaded pending row must restore its
    spend into the budget meter without appearing as a completed run in
    ``list_recent_runs()``, the same as it never would have without a
    restart (a follow-up Devin finding on that same fix).
    """
    db_path = tmp_path / "batch_restart_state.db"
    agent = ModelAgent("general_agent", "model-x", tags=("reasoning", "writing"))
    orchestrator = TaskOrchestrator(
        [agent],
        client=_CountingClient(),  # every item reports completion_tokens=6
        price_per_million={"model-x": 10.0},
        budget_max_output_tokens=10,  # below the two-item aggregate (12)
        state_db=str(db_path),
    )

    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        with pytest.raises(orchestrator_module.BudgetExceededError):
            orchestrator.batch_route(["task one", "task three"])
    orchestrator.close()

    restarted = TaskOrchestrator(
        [agent],
        client=_CountingClient(),
        price_per_million={"model-x": 10.0},
        budget_max_output_tokens=10,
        state_db=str(db_path),
    )
    try:
        assert restarted.budget_status()["spent_output_tokens"] == 12
        assert restarted.budget_status()["exceeded"] is True
        # The reloaded pending rows restore spend but must not surface as
        # completed runs -- they were never judged.
        assert restarted.list_recent_runs(page_size=10) == []
        with pytest.raises(orchestrator_module.BudgetExceededError):
            restarted.batch_route(["task five"])
    finally:
        restarted.close()


def test_batch_route_budget_meter_includes_reported_judge_usage() -> None:
    class _UsageJudge(_ScriptedFastJudge):
        def judge(self, **kwargs):
            result = super().judge(**kwargs)
            result.usage = {"completion_tokens": 2}
            return result

    components = replace(_scripted_fast_components(), judge_cls=_UsageJudge)
    orchestrator = _orch(_CountingClient())

    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=components,
    ):
        orchestrator.batch_route(["task one"])

    assert orchestrator.budget_status()["spent_output_tokens"] == 8
    spend = orchestrator.spend_analytics()
    assert spend["totals"]["estimated_output_tokens"] == 8
    assert spend["by_model"][0]["output_tokens"] == 8
    assert spend["by_model"][0]["estimated_cost_usd"] == pytest.approx(0.00008)


def test_batch_route_judge_usage_survives_agent_pool_model_change() -> None:
    """A judge's historical spend must stay pinned to the model that actually served
    it, not silently reattribute when the serving agent's id is later reused for a
    different model (Devin review on #961: judge model was re-resolved from the live
    pool on every read, unlike worker steps, whose ``model_name`` is pinned at write
    time)."""

    class _UsageJudge(_ScriptedFastJudge):
        def judge(self, **kwargs):
            result = super().judge(**kwargs)
            result.usage = {"completion_tokens": 2}
            return result

    components = replace(_scripted_fast_components(), judge_cls=_UsageJudge)
    orchestrator = _orch(_CountingClient())

    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=components,
    ):
        orchestrator.batch_route(["task one"])

    assert orchestrator.budget_status()["spent_output_tokens"] == 8

    # Re-discovery upserts the same agent id under a new (unpriced) model -- the
    # real-world path that reuses an agent id for a different model and triggers
    # _rebuild_budget_meter().
    orchestrator.sync_discovered_agents(
        [ModelAgent("general_agent", "model-y", tags=("reasoning", "writing"))]
    )

    assert orchestrator.budget_status()["spent_output_tokens"] == 8
    spend = orchestrator.spend_analytics()
    assert spend["totals"]["estimated_output_tokens"] == 8
    by_model = {row["model"]: row for row in spend["by_model"]}
    assert "model-y" not in by_model  # no historical spend leaks onto the new model
    assert by_model["model-x"]["output_tokens"] == 8  # worker (6) + judge (2), pinned
    assert by_model["model-x"]["estimated_cost_usd"] == pytest.approx(0.00008)


def test_batch_route_persists_earlier_group_spend_when_a_later_group_fails() -> None:
    """One provider group's real, already-incurred spend must survive a
    completely unrelated later group's batch_chat() failure.

    Devin review on #961: batch_route executes one batch_chat() call per
    distinct worker agent ("group"), building every group's results into one
    flat dict before persisting any of them. If an earlier group's call
    already succeeded (real, incurred provider spend) and a later group's
    call then raised, the whole batch_route call raised before the earlier
    group's rows were ever persisted -- losing that real spend from budget
    accounting entirely, not just leaving it pending.
    """
    agent_a = ModelAgent("agent_a", "model-a", tags=("reasoning", "writing"))
    agent_b = ModelAgent("agent_b", "model-b", tags=("reasoning", "writing"))

    class _SecondGroupFailsClient(_CountingClient):
        def batch_chat(self, agent, requests, temperature=0.2, poll_interval=5.0, poll_timeout=3600.0):  # type: ignore[override]
            if agent.id == "agent_b":
                raise RuntimeError("provider outage for agent_b's batch")
            return super().batch_chat(agent, requests, temperature, poll_interval, poll_timeout)

    client = _SecondGroupFailsClient()
    orchestrator = TaskOrchestrator([agent_a, agent_b], client=client)
    agent_by_prompt = {"task one": agent_a, "task two": agent_b}

    with patch.object(
        orchestrator,
        "_select_agent",
        side_effect=lambda text, role, **kwargs: agent_by_prompt[text],
    ):
        with pytest.raises(RuntimeError, match="provider outage for agent_b"):
            orchestrator.batch_route(["task one", "task two"])

    # agent_a's group already succeeded and incurred real spend (6 output
    # tokens per _CountingClient) before agent_b's group failed -- that
    # spend must not be lost.
    assert orchestrator.budget_status()["spent_output_tokens"] == 6
    pending = [
        record for record in orchestrator._workflow_runs.values()  # noqa: SLF001
        if record.get("pending_verification")
    ]
    assert len(pending) == 1
    assert pending[0]["trace"][0]["agent_id"] == "agent_a"


def test_pending_batch_rows_excluded_from_completed_run_counts() -> None:
    """A not-yet-judged batch row must not inflate completed-run KPIs.

    Devin review on #961: count_workflow_runs(), analytics_snapshot(), and
    sales_readiness_report() read _workflow_runs directly, so an interrupted
    batch's pending_verification rows -- deliberately kept out of
    _run_order/list_recent_runs() -- still counted as finished results in
    those completed-run consumers.
    """
    client = _CountingClient()  # every item reports completion_tokens=6
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing"))],
        client=client,
        price_per_million={"model-x": 10.0},
        budget_max_output_tokens=10,  # below the two-item aggregate (12)
    )

    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        with pytest.raises(orchestrator_module.BudgetExceededError):
            orchestrator.batch_route(["task one", "task three"])

    # Both items' worker calls completed and are pending, but neither was
    # ever judged.
    assert len(orchestrator._workflow_runs) == 2  # noqa: SLF001
    assert orchestrator.count_workflow_runs() == 0
    assert orchestrator.list_recent_runs() == []
    snapshot = orchestrator.analytics_snapshot()
    route_driver = next(
        driver for driver in snapshot["drivers"]
        if driver["metric_name"] == "route_versus_conduct_mix"
    )
    assert route_driver["counts"]["route"] == 0


def test_batch_route_blocks_a_later_group_once_an_earlier_group_exhausts_budget() -> None:
    """A later provider group must not start once an earlier group's real,
    already-persisted spend alone already exceeds the cap.

    Devin review on #961: batch_route's budget check ran once at entry,
    before any group's batch_chat() call. Once each group's spend started
    persisting immediately (a prior fix on this same PR), a later group
    could still start unconditionally even though the earlier group's own
    spend had already blown through the cap -- incurring avoidable
    provider charges on a batch that was already over budget.
    """
    agent_a = ModelAgent("agent_a", "model-a", tags=("reasoning", "writing"))
    agent_b = ModelAgent("agent_b", "model-b", tags=("reasoning", "writing"))
    client = _CountingClient()  # every item reports completion_tokens=6
    orchestrator = TaskOrchestrator(
        [agent_a, agent_b],
        client=client,
        price_per_million={"model-a": 10.0, "model-b": 10.0},
        budget_max_output_tokens=6,  # exactly agent_a's group's own spend
    )
    agent_by_prompt = {"task one": agent_a, "task two": agent_b}

    with patch.object(
        orchestrator,
        "_select_agent",
        side_effect=lambda text, role, **kwargs: agent_by_prompt[text],
    ):
        with pytest.raises(orchestrator_module.BudgetExceededError):
            orchestrator.batch_route(["task one", "task two"])

    # agent_a's group ran and persisted; agent_b's group must never have
    # started a provider call at all.
    assert client.batch_calls == 1
    assert orchestrator.budget_status()["spent_output_tokens"] == 6
    pending = [
        record for record in orchestrator._workflow_runs.values()  # noqa: SLF001
        if record.get("pending_verification")
    ]
    assert len(pending) == 1
    assert pending[0]["trace"][0]["agent_id"] == "agent_a"


def test_batch_route_disabled_judging_never_strands_a_completed_answer_on_budget() -> None:
    """With realtime_judge off, an already-exhausted budget must not block
    finalizing an already-completed, already-paid-for worker answer.

    Devin review on #961: the pre-judge-call budget checkpoint fired
    regardless of policy.realtime_judge, even though _realtime_route_judge
    makes no provider call at all when judging is disabled -- there was no
    next spend left for that checkpoint to gate, so it could only ever
    strand a result that needed no further spend to finalize.
    """
    client = _CountingClient()  # every item reports completion_tokens=6
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing"))],
        client=client,
        price_per_million={"model-x": 10.0},
        budget_max_output_tokens=6,  # exactly the one item's own worker spend
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)

    records = orchestrator.batch_route(["task one"])

    assert len(records) == 1
    assert records[0]["verification"]["accepted"] is True
    assert records[0]["verification"]["reason"] == "single route path"
    assert orchestrator.count_workflow_runs() == 1


def test_batch_route_finalizes_completed_group_before_blocking_a_later_one_when_judging_is_free() -> None:
    """An earlier group's completed rows must not stay pending forever just
    because a later, unrelated group's own budget check blocks it.

    Devin review on #961: batch_route persists each completed group as
    pending but defers all judging to a second pass over every group. The
    inter-group budget checkpoint can therefore raise before that second
    pass ever reaches an already-completed earlier group -- and when
    realtime_judge is off, finalizing that group costs nothing, so there is
    no reason to leave its answers stuck invisible as pending_verification
    indefinitely (batch_route never resumes/retries a specific pending row
    on its own).
    """
    agent_a = ModelAgent("agent_a", "model-a", tags=("reasoning", "writing"))
    agent_b = ModelAgent("agent_b", "model-b", tags=("reasoning", "writing"))
    client = _CountingClient()  # every item reports completion_tokens=6
    orchestrator = TaskOrchestrator(
        [agent_a, agent_b],
        client=client,
        price_per_million={"model-a": 10.0, "model-b": 10.0},
        budget_max_output_tokens=6,  # exactly agent_a's group's own spend
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    agent_by_prompt = {"task one": agent_a, "task two": agent_b}

    with patch.object(
        orchestrator,
        "_select_agent",
        side_effect=lambda text, role, **kwargs: agent_by_prompt[text],
    ):
        with pytest.raises(orchestrator_module.BudgetExceededError):
            orchestrator.batch_route(["task one", "task two"])

    # agent_b's group never started a provider call (still correctly
    # blocked), but agent_a's group -- already complete before the block --
    # must be a finalized, visible run, not stuck pending.
    assert client.batch_calls == 1
    assert orchestrator.count_workflow_runs() == 1
    [finalized] = orchestrator.list_recent_runs()
    assert finalized["trace"][0]["agent_id"] == "agent_a"
    assert finalized["verification"] == {
        "accepted": True,
        "reason": "single route path",
        "verifier_output": finalized["answer"],
        "judge": "model",
    }


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
