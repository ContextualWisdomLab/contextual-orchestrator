"""No-heuristics contracts for request-local candidate controls."""

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import _validate_routing


def test_exclusion_membership_has_no_repository_authored_cardinality_cutoff() -> None:
    """Request membership is bounded by normal request parsing, not a magic route count."""
    excluded = [f"candidate_{index}" for index in range(40)]
    routing = _validate_routing(
        {"exclude_candidate_ids": excluded}, allow_candidate_controls=True
    )
    assert routing == {"exclude_candidate_ids": excluded}

    orchestrator = TaskOrchestrator(
        [ModelAgent(candidate, f"model-{index}") for index, candidate in enumerate(excluded)]
        + [ModelAgent("remaining_candidate", "remaining-model")]
    )
    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": excluded}, model_name=TaskOrchestrator.AUTO_MODEL
    ):
        assert orchestrator._request_candidate_allowed(orchestrator._agent("remaining_candidate"))


def test_served_candidate_evidence_fails_closed_without_explicit_identity() -> None:
    """Never infer the serving candidate from output equality or trace position."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_agent", "worker-model"), ModelAgent("excluded_agent", "excluded-model")]
    )
    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["excluded_agent"]}
    ):
        orchestrator._record_candidate_attempt("worker_agent")
        evidence = orchestrator._candidate_routing_evidence(
            {
                "answer": "duplicate output",
                "trace": [
                    {"id": 0, "agent_id": "worker_agent", "output": "duplicate output"}
                ],
            }
        )
    assert evidence is not None
    assert evidence["attempted_candidate_ids"] == ["worker_agent"]
    assert "served_candidate_id" not in evidence


def test_explicit_served_identity_remains_auditable_without_answering_step_id() -> None:
    """Provider-shaped paths may report a serving identity when they record it explicitly."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_agent", "worker-model"), ModelAgent("excluded_agent", "excluded-model")]
    )
    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["excluded_agent"]}
    ):
        orchestrator._record_candidate_attempt("worker_agent")
        evidence = orchestrator._candidate_routing_evidence(
            {
                "trace": [
                    {
                        "agent_id": "worker_agent",
                        "served_agent_id": "worker_agent",
                    }
                ]
            }
        )
    assert evidence is not None
    assert evidence["served_candidate_id"] == "worker_agent"
