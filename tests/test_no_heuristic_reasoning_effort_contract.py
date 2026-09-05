"""Regression contract for evidence-only test-time-compute policy."""

from __future__ import annotations

import pytest

from contextual_orchestrator import reasoning_effort_profile as rep


def test_hand_authored_default_role_catalog_is_not_decision_authority() -> None:
    """A role-name lookup table must not allocate reasoning effort or token budget."""
    with pytest.raises(rep.EffortProfileError, match="heuristic|evidence"):
        rep.default_role_effort_catalog()


def test_synthetic_theta_and_token_estimators_fail_closed() -> None:
    """Invented shrinkage/token formulas are not measurements of compute quality or use."""
    with pytest.raises(rep.EffortProfileError, match="heuristic|measured|evidence"):
        rep.estimate_theta(
            (-1.0, 0.0, 1.0),
            reasoning_effort="high",
            extra_workflow_steps=1,
            temperature=0.2,
        )
    with pytest.raises(rep.EffortProfileError, match="heuristic|measured|evidence"):
        rep.estimate_theta_rmse(
            (-1.0, 0.0, 1.0),
            reasoning_effort="high",
            extra_workflow_steps=1,
            temperature=0.2,
        )
    with pytest.raises(rep.EffortProfileError, match="heuristic|provider|evidence"):
        rep._estimated_tokens_used("high", 1, 1, 1024)
    with pytest.raises(rep.EffortProfileError, match="heuristic|measured|evidence"):
        rep.run_equal_budget_ablation((-1.0, 0.0, 1.0))


def test_no_fixed_rmse_improvement_threshold_can_unlock_production() -> None:
    """A hand-selected improvement percentage cannot authorize a production default."""
    assert rep.PRODUCTION_RMSE_IMPROVEMENT_THRESHOLD is None
    assert (
        rep.production_default_change_allowed(
            {
                "single_model_baseline": {"rmse": 1.0},
                "role_differentiated": {"rmse": 0.0},
                "measurement_status": "measured",
                "robustness_passed": True,
            }
        )
        is False
    )
