"""Public optimizer contracts reject invalid per-task quality, not just invalid means."""

import math
from unittest.mock import patch

import pytest

from test_batch_optimizer import _CountingClient, _orch
from contextual_orchestrator.orchestrator import evolve_orchestration, optimize_orchestration


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
