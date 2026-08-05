"""Behavioral tests for graph-aware test-time reasoning allocation."""

from __future__ import annotations

import pytest

from contextual_orchestrator.reasoning_control import (
    ReasoningDecision,
    ReasoningPolicy,
    ReasoningProfile,
    ReasoningWorkload,
    WorkflowReasoningCursor,
    select_reasoning_decision,
    workload_for_trace_row,
)
from contextual_orchestrator.reasoning_runtime import (
    current_reasoning_workload,
    reasoning_workload_override,
)

from reasoning_fakes import make_orchestrator


def _profile() -> ReasoningProfile:
    """Return the four-level model capability used by structural tests."""
    return ReasoningProfile(
        supported_levels=("minimal", "low", "medium", "high"),
        default_level="low",
        maximum_level="high",
    )


def _messages(prior: str) -> list[dict[str, str]]:
    """Build the repository's bounded accessed-work prompt shape."""
    return [
        {
            "role": "user",
            "content": (
                "Original task:\nSummarize this note.\n\n"
                f"Accessed prior work:\n{prior}\n\nSubtask:\nContinue."
            ),
        }
    ]


def test_workload_round_trips_without_a_latency_control() -> None:
    workload = ReasoningWorkload(3, 5, 3, 4, 3)
    assert ReasoningWorkload.from_mapping(workload.to_dict()) == workload
    assert "latency" not in workload.to_dict()


@pytest.mark.parametrize(
    "value",
    [
        {"unknown_key": 1},
        {"workflow_step_index": True},
        {"workflow_step_count": 0},
        {"decomposition_count": 0},
        {"workflow_step_index": -1},
        {"workflow_step_index": 1, "workflow_step_count": 1},
        {"workflow_step_index": 0, "recursion_depth": 1},
        {"workflow_step_index": 0, "accessible_step_count": 1},
        {"workflow_step_count": 1, "decomposition_count": 2},
    ],
)
def test_workload_rejects_ambiguous_or_impossible_topology(value: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ReasoningWorkload.from_mapping(value)


def test_cursor_tracks_workflow_position_recursion_and_access_fan_in() -> None:
    cursor = WorkflowReasoningCursor(4)
    first = cursor.observe(_messages("(none)"))
    second = cursor.observe(_messages("Step 0: plan"))
    third = cursor.observe(_messages("Step 0: plan\nStep 1: work"))
    fourth = cursor.observe(_messages("Step 0: plan\nStep 1: work\nStep 2: verified"))

    assert first == ReasoningWorkload(0, 4, 0, 4, 0)
    assert second == ReasoningWorkload(1, 4, 1, 4, 1)
    assert third == ReasoningWorkload(2, 4, 2, 4, 2)
    assert fourth == ReasoningWorkload(3, 4, 3, 4, 3)
    assert cursor.observe(_messages("unused")) is None


def test_cursor_accepts_generated_plan_size_before_execution_only() -> None:
    cursor = WorkflowReasoningCursor(4)
    cursor.set_plan_size(5)
    assert cursor.observe(_messages("(none)")) == ReasoningWorkload(0, 5, 0, 5, 0)
    with pytest.raises(RuntimeError, match="cannot change"):
        cursor.set_plan_size(3)
    with pytest.raises(ValueError, match="positive integer"):
        WorkflowReasoningCursor(0)
    with pytest.raises(ValueError, match="positive integer"):
        WorkflowReasoningCursor(2, decomposition_count=0)
    with pytest.raises(ValueError, match="cannot exceed"):
        WorkflowReasoningCursor(2, decomposition_count=3)
    with pytest.raises(ValueError, match="positive integer"):
        WorkflowReasoningCursor(2).set_plan_size(False)


def test_cursor_infers_template_access_when_fake_prior_outputs_have_no_step_labels() -> None:
    cursor = WorkflowReasoningCursor(4)
    assert cursor.observe(_messages("(none)")) == ReasoningWorkload(0, 4, 0, 4, 0)
    assert cursor.observe(_messages("unlabelled plan output")) == ReasoningWorkload(
        1,
        4,
        1,
        4,
        1,
    )
    direct = WorkflowReasoningCursor(1)
    assert direct.observe([{"role": "user", "content": "plain direct request"}]) == ReasoningWorkload()


def test_structural_signals_raise_compute_without_a_speed_objective() -> None:
    direct = select_reasoning_decision(
        _profile(),
        ReasoningPolicy(),
        "Summarize this note.",
        "worker",
        workload=ReasoningWorkload(),
    )
    deep = select_reasoning_decision(
        _profile(),
        ReasoningPolicy(),
        "Summarize this note.",
        "worker",
        workload={
            "workflow_step_index": 3,
            "workflow_step_count": 5,
            "recursion_depth": 3,
            "decomposition_count": 4,
            "accessible_step_count": 3,
        },
    )
    assert direct is not None and direct.level == "low"
    assert deep is not None and deep.level == "high"
    assert deep.workload == ReasoningWorkload(3, 5, 3, 4, 3)
    assert {
        "decomposed_workflow",
        "recursive_workflow_depth",
        "access_list_fan_in",
        "late_workflow_integration",
    }.issubset(deep.factors)
    assert all("latency" not in factor and "speed" not in factor for factor in deep.factors)


def test_fixed_policy_records_structure_but_does_not_adapt_the_fixed_level() -> None:
    workload = ReasoningWorkload(2, 4, 2, 4, 2)
    decision = select_reasoning_decision(
        _profile(),
        ReasoningPolicy(strategy="fixed", fixed_level="medium", max_escalations=0),
        "complex task",
        "verifier",
        workload=workload,
    )
    assert decision == ReasoningDecision(
        "medium",
        "fixed_policy",
        "verifier",
        0,
        ("fixed_policy",),
        workload=workload,
    )
    assert decision.to_dict()["workload"] == workload.to_dict()
    with pytest.raises(ValueError, match="workload must be"):
        select_reasoning_decision(
            _profile(),
            ReasoningPolicy(),
            "task",
            "worker",
            workload="invalid",
        )


def test_trace_reconstruction_uses_actual_access_lists() -> None:
    trace = [
        {"id": 0, "access": []},
        {"id": 1, "access": [0]},
        {"id": 2, "access": [0, 1]},
        {"id": 3, "access": [0, 1, 2]},
    ]
    assert workload_for_trace_row(trace[3], trace) == ReasoningWorkload(3, 4, 3, 4, 3)
    with pytest.raises(ValueError, match="at least one"):
        workload_for_trace_row({"id": 0}, [])
    with pytest.raises(ValueError, match="non-negative integer"):
        workload_for_trace_row({"id": "three"}, trace)


def test_workload_override_is_request_local_and_type_safe() -> None:
    workload = ReasoningWorkload(1, 4, 1, 4, 1)
    assert current_reasoning_workload() is None
    with reasoning_workload_override(workload):
        assert current_reasoning_workload() == workload
    assert current_reasoning_workload() is None
    with pytest.raises(TypeError, match="ReasoningWorkload"):
        with reasoning_workload_override("invalid"):
            pass


def test_conduct_trace_records_role_specific_graph_workload() -> None:
    orchestrator = make_orchestrator()
    result = orchestrator.conduct(
        [{"role": "user", "content": "Summarize this note."}]
    )
    workloads = [
        row["reasoning"]["decision"]["workload"]
        for row in result["trace"]
    ]
    assert workloads == [
        ReasoningWorkload(0, 4, 0, 4, 0).to_dict(),
        ReasoningWorkload(1, 4, 1, 4, 1).to_dict(),
        ReasoningWorkload(2, 4, 2, 4, 2).to_dict(),
        ReasoningWorkload(3, 4, 3, 4, 3).to_dict(),
    ]
    escalation = result["reasoning_escalation"]
    assert escalation["from_level"] == "low"
    assert escalation["to_level"] == "medium"
    assert result["trace"][1]["reasoning"]["decision"]["level"] == "medium"
    assert result["trace"][2]["reasoning"]["decision"]["level"] == "high"


def test_route_trace_remains_a_single_step_workload() -> None:
    orchestrator = make_orchestrator()
    result = orchestrator.route_once(
        [{"role": "user", "content": "Summarize this note."}]
    )
    decision = result["trace"][0]["reasoning"]["decision"]
    assert decision["level"] == "low"
    assert decision["workload"] == ReasoningWorkload().to_dict()
