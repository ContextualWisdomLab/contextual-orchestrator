"""Focused branch coverage for structural reasoning workload failures."""

from __future__ import annotations

import pytest

from contextual_orchestrator._reasoning_workflow import _retry_rejected_worker_once
from contextual_orchestrator.reasoning_control import ReasoningDecision, ReasoningWorkload

from reasoning_fakes import make_orchestrator


def test_workload_from_mapping_rejects_non_object() -> None:
    """A JSON array cannot masquerade as named workflow topology evidence."""
    with pytest.raises(ValueError, match="must be an object"):
        ReasoningWorkload.from_mapping([])  # type: ignore[arg-type]


def test_workload_trace_target_must_belong_to_workflow() -> None:
    """A target row outside the observed trace cannot receive invented depth."""
    with pytest.raises(ValueError, match="outside the workflow"):
        ReasoningWorkload.from_mapping(
            {
                "workflow_step_index": 0,
                "workflow_step_count": 1,
            }
        )
        from contextual_orchestrator.reasoning_control import workload_for_trace_row

        workload_for_trace_row({"id": 2}, [{"id": 0, "access": []}])


def test_reasoning_decision_rejects_untyped_workload() -> None:
    """Decision evidence accepts only a validated ReasoningWorkload value."""
    with pytest.raises(ValueError, match="ReasoningWorkload or None"):
        ReasoningDecision(
            "low",
            "adaptive_policy",
            "worker",
            0,
            ("profile_default",),
            workload="invalid",  # type: ignore[arg-type]
        )


def test_retry_stops_when_trace_agent_no_longer_exists() -> None:
    """A stale trace identity cannot trigger recomputation against another agent."""
    orchestrator = make_orchestrator()
    result = {
        "verification": {"accepted": False},
        "trace": [
            {
                "id": 1,
                "role": "worker",
                "agent_id": "missing_agent",
                "access": [0],
                "reasoning": {
                    "decision": {
                        "level": "low",
                        "source": "adaptive_policy",
                        "complexity_score": 0,
                        "factors": ["profile_default"],
                        "escalation_index": 0,
                        "workload": ReasoningWorkload(1, 2, 1, 2, 1).to_dict(),
                    }
                },
            }
        ],
    }
    _retry_rejected_worker_once(orchestrator, result, "task")
    assert "reasoning_escalation" not in result
