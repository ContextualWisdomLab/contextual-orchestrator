"""Public optimizer contracts reject invalid per-task quality, not just invalid means."""

import math
import json
from types import SimpleNamespace
from decimal import Decimal
from unittest.mock import patch

import pytest

from test_batch_optimizer import _CountingClient, _orch
from contextual_orchestrator.orchestrator import evolve_orchestration, optimize_orchestration


@pytest.mark.parametrize("optimizer_kind", ["optimize", "evolve"])
@pytest.mark.parametrize("record_count", [0, 1, 3])
def test_batch_cardinality_rejected_before_scoring(optimizer_kind, record_count):
    """Incomplete or extra custom-engine results cannot rank a partial task set."""
    callback_calls = []
    candidate_engine = SimpleNamespace(
        batch_route=lambda prompts: [{"answer": "unit answer"}] * record_count,
        spend_analytics=lambda: {"totals": {"cost_usd": 0.1}},
    )
    task_rows = [{"prompt": "first task"}, {"prompt": "second task"}]

    def quality_score(task_row, answer_text):
        """Track whether malformed batches reach the evaluation callback."""
        callback_calls.append(task_row)
        return 1.0

    with pytest.raises(ValueError, match="batch result count must match task count") as caught_error:
        if optimizer_kind == "evolve":
            evolve_orchestration(lambda config: candidate_engine, {"mode": ["route"]},
                task_rows, quality_score, generations=1, population=1, use_batch=True)
        else:
            optimize_orchestration([{"name": "reference", "orchestrator": candidate_engine}],
                task_rows, quality_score, use_batch=True)
    assert callback_calls == []
    assert caught_error.value.optimizer_usage[0]["totals"]["cost_usd"] == 0.1


def _evaluate_scores(score_values, optimizer_kind, use_batch, execution_mode="route"):
    """Evaluate mock answers through the public serial and batch optimizer APIs."""
    task_rows = [{"prompt": "reference task", "score_value": value} for value in score_values]
    def quality_score(task_row, answer_text):
        """Return the declared test score without making a provider call."""
        return task_row["score_value"]

    with patch("contextual_orchestrator.orchestrator._resolve_fast_mlsirm_components", return_value=None):
        if optimizer_kind == "evolve":
            return evolve_orchestration(
                lambda config: _orch(_CountingClient()), {"mode": [execution_mode]},
                task_rows, quality_score, generations=1, population=1, use_batch=use_batch,
            )
        return optimize_orchestration(
            [{"name": "reference_config", "orchestrator": _orch(_CountingClient()), "mode": execution_mode}],
            task_rows, quality_score, use_batch=use_batch,
        )


@pytest.mark.parametrize("optimizer_kind", ["optimize", "evolve"])
@pytest.mark.parametrize("execution_mode", ["route", "auto", "conduct"])
@pytest.mark.parametrize("use_batch", [False, True])
@pytest.mark.parametrize("score_values", [[math.nan], [math.inf], [-math.inf], [-0.1], [1.1], [-0.1, 1.1], [0.5, 1.1]])
def test_invalid_task_quality_rejected(score_values, optimizer_kind, use_batch, execution_mode):
    """Invalid values cannot enter recommendations even when their mean is valid."""
    with pytest.raises(ValueError, match=r"quality scores must be finite and in \[0, 1\]"):
        _evaluate_scores(score_values, optimizer_kind, use_batch, execution_mode)


@pytest.mark.parametrize("optimizer_kind", ["optimize", "evolve"])
@pytest.mark.parametrize("execution_mode", ["route", "auto", "conduct"])
@pytest.mark.parametrize("use_batch", [False, True])
@pytest.mark.parametrize("score_values", [[0.0], [1.0], [0.25, 0.75], [False, True]])
def test_valid_task_quality_preserved(score_values, optimizer_kind, use_batch, execution_mode):
    """Endpoints, fractional scores, and predicate callbacks retain their meaning."""
    result_rows = _evaluate_scores(score_values, optimizer_kind, use_batch, execution_mode)["results"]
    assert result_rows[0]["quality"] == sum(score_values) / len(score_values)


@pytest.mark.parametrize("optimizer_kind", ["optimize", "evolve"])
@pytest.mark.parametrize("execution_mode", ["route", "auto", "conduct"])
@pytest.mark.parametrize("use_batch", [False, True])
def test_score_rejection_preserves_completed_usage(optimizer_kind, execution_mode, use_batch):
    """Rejecting an evaluation must not erase already completed provider work."""
    candidate_engine = _orch(_CountingClient())
    task_rows = [{"prompt": "reference task"}, {"prompt": "second reference task"}]
    with patch("contextual_orchestrator.orchestrator._resolve_fast_mlsirm_components", return_value=None):
        with pytest.raises(ValueError, match="quality scores must be finite"):
            if optimizer_kind == "evolve":
                evolve_orchestration(lambda config: candidate_engine, {"mode": [execution_mode]},
                    task_rows, lambda task, answer: math.nan, generations=1, population=1,
                    use_batch=use_batch)
            else:
                optimize_orchestration([{"name": "reference_config", "orchestrator": candidate_engine,
                    "mode": execution_mode}], task_rows, lambda task, answer: math.nan,
                    use_batch=use_batch)
    usage_totals = candidate_engine.spend_analytics()["totals"]
    assert usage_totals["run_count"] == len(task_rows)
    assert len(candidate_engine._workflow_runs) == len(task_rows)
    if use_batch and execution_mode == "route":
        assert candidate_engine.spend_analytics()["by_model"][0]["output_tokens"] == 12


@pytest.mark.parametrize("optimizer_kind", ["optimize", "evolve"])
@pytest.mark.parametrize("execution_mode", ["route", "auto", "conduct"])
@pytest.mark.parametrize("use_batch", [False, True])
@pytest.mark.parametrize("failure_kind", ["domain", "callback", "conversion"])
def test_discarded_factory_exposes_completed_usage(optimizer_kind, execution_mode, use_batch, failure_kind):
    """An exception retains safe snapshots for earlier and failed evaluations."""
    score_calls = 0
    def score_value(task_row, answer_text):
        nonlocal score_calls
        score_calls += 1
        if score_calls <= 2:
            return 0.5
        if failure_kind == "callback":
            raise LookupError("scorer failed")
        return "not a number" if failure_kind == "conversion" else math.nan

    task_rows = [{"prompt": "private evaluation prompt"}] * 2
    with patch("contextual_orchestrator.orchestrator._resolve_fast_mlsirm_components", return_value=None):
        with pytest.raises((ValueError, LookupError)) as caught_error:
            if optimizer_kind == "evolve":
                evolve_orchestration(lambda config: _orch(_CountingClient()),
                    {"mode": [execution_mode], "trial_id": [1, 2]}, task_rows,
                    score_value, generations=1, population=2, use_batch=use_batch)
            else:
                optimize_orchestration([
                    {"name": "private candidate", "mode": execution_mode, "orchestrator": _orch(_CountingClient())}
                    for _ in range(2)], task_rows, score_value, use_batch=use_batch)
    usage_rows = caught_error.value.optimizer_usage
    assert len(usage_rows) == 2
    assert [row["evaluation_index"] for row in usage_rows] == [0, 1]
    assert all(row["scope"] == "cumulative_engine_snapshot" for row in usage_rows)
    assert usage_rows[0]["totals"]["run_count"] == 2
    expected_runs = 2 if failure_kind == "domain" or use_batch and execution_mode == "route" else 1
    assert usage_rows[1]["totals"]["run_count"] == expected_runs
    assert set(usage_rows[1]["totals"]) == {"run_count", "prompt_tokens", "output_tokens", "prompt_tokens_source", "cost_usd", "currency"}
    assert "private" not in json.dumps(usage_rows)
    assert "general_agent" not in json.dumps(usage_rows)
    if use_batch and execution_mode == "route":
        assert usage_rows[1]["totals"]["output_tokens"] == 12
    else:
        assert usage_rows[1]["totals"]["cost_usd"] is None
    assert type(caught_error.value) is (LookupError if failure_kind == "callback" else ValueError)


def test_retained_engine_usage_is_explicitly_cumulative():
    """Prior work remains distinguishable from invocation-only billing claims."""
    candidate_engine = _orch(_CountingClient())
    with patch("contextual_orchestrator.orchestrator._resolve_fast_mlsirm_components", return_value=None):
        candidate_engine.batch_route(["prior private prompt"])
        with pytest.raises(ValueError) as caught_error:
            optimize_orchestration([{"name": "private", "mode": "route", "orchestrator": candidate_engine}],
                [{"prompt": "new private prompt"}], lambda task, answer: math.nan, use_batch=True)
    usage_row = caught_error.value.optimizer_usage[0]
    assert usage_row["scope"] == "cumulative_engine_snapshot"
    assert usage_row["totals"]["run_count"] == 2
    assert usage_row["totals"]["output_tokens"] == 12


def test_usage_snapshot_failure_preserves_original_exception():
    """Broken analytics must neither mask the scorer failure nor invent zero spend."""
    original_error = LookupError("scorer failed")
    with patch("contextual_orchestrator.orchestrator._resolve_fast_mlsirm_components", return_value=None):
        with patch("contextual_orchestrator.orchestrator.TaskOrchestrator.spend_analytics",
                   side_effect=RuntimeError("private analytics details")):
            with pytest.raises(LookupError) as caught_error:
                evolve_orchestration(lambda config: _orch(_CountingClient()), {"mode": ["route"]},
                    [{"prompt": "private prompt"}], lambda task, answer: (_ for _ in ()).throw(original_error),
                    generations=1, population=1)
    assert caught_error.value is original_error
    assert caught_error.value.optimizer_usage == ({"evaluation_index": 0,
        "scope": "cumulative_engine_snapshot", "snapshot_status": "unavailable", "totals": None},)


def test_minimal_analytics_contract_remains_supported():
    """Optional usage fields do not expand the successful optimizer contract."""
    candidate_engine = _orch(_CountingClient())
    with patch("contextual_orchestrator.orchestrator._resolve_fast_mlsirm_components", return_value=None):
        with patch.object(candidate_engine, "spend_analytics", return_value={"totals": {"cost_usd": None}}):
            report = optimize_orchestration([{"name": "reference", "orchestrator": candidate_engine}],
                [{"prompt": "reference task"}], lambda task, answer: 0.5)
            assert report["results"][0]["quality"] == 0.5
            with pytest.raises(ValueError) as caught_error:
                optimize_orchestration([{"name": "reference", "orchestrator": candidate_engine}],
                    [{"prompt": "reference task"}], lambda task, answer: math.nan)
    assert caught_error.value.optimizer_usage[0]["totals"]["output_tokens"] is None


def test_readonly_exception_usage_preserves_original_failure():
    """Read-only properties cannot mask the original error or discard decimal cost."""
    class ReadonlyUsageError(LookupError):
        @property
        def optimizer_usage(self):
            return None

    original_error = ReadonlyUsageError("scorer failed")
    def failed_score(task_row, answer_text):
        raise original_error
    with patch("contextual_orchestrator.orchestrator._resolve_fast_mlsirm_components", return_value=None):
        with patch("contextual_orchestrator.orchestrator.TaskOrchestrator.spend_analytics",
                   return_value={"totals": {"cost_usd": Decimal("0.1")}}):
            with pytest.raises(ReadonlyUsageError) as caught_error:
                evolve_orchestration(lambda config: _orch(_CountingClient()), {"mode": ["route"]},
                    [{"prompt": "private prompt"}], failed_score, generations=1, population=1)
    assert caught_error.value is original_error
    usage_rows = vars(original_error)["optimizer_usage"]
    assert usage_rows[0]["totals"]["cost_usd"] == Decimal("0.1")
