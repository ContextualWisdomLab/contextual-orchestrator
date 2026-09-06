"""Regression contract for ProviderResponseError detail composition."""

from __future__ import annotations

from contextual_orchestrator.orchestrator import ProviderResponseError


def test_provider_response_error_detail_stays_mutable_with_failover_evidence() -> None:
    """Sibling error types may extend detail while failover evidence stays visible."""
    error = ProviderResponseError(
        "structured output exhausted",
        attempts=[
            {
                "provider_name": "provider-a",
                "attempt_number": 1,
                "transport": "chat",
                "phase": "structured_output",
                "failover_decision": "continue",
            }
        ],
        stop_reason="candidate_pool_exhausted",
    )

    error.detail = {"failure_kind": "structured_output_exhausted"}
    error.detail["workflow_run_id"] = "run-123"

    assert error.detail["failure_kind"] == "structured_output_exhausted"
    assert error.detail["workflow_run_id"] == "run-123"
    assert error.detail["attempts"] == error.attempts
    assert error.detail["stop_reason"] == "candidate_pool_exhausted"
