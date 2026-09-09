"""Route decision receipt latency contract for accepted-request accounting.

Covers issue #1110 ``feat(telemetry): measure accepted-request to durable
route-decision latency``. Desired owner-side contract is event
``route_decision_receipt`` with fields ``admission_id``, ``decision_attempt``,
``admitted_first_at``, ``selection_done_at``, ``receipt_acked_at``,
``policy_revision``, ``route_mode``, ``receipt_status`` on one monotonic clock,
with initial versus failover attempts distinct and failed write or cancel
producing no success receipt.
"""

from __future__ import annotations

import time as time_module

from contextual_orchestrator import ModelAgent, TaskOrchestrator


def _build_stub_orchestrator() -> TaskOrchestrator:
    """Build one deterministic orchestrator with stub agents."""
    stub_agent = ModelAgent(
        "route_receipt_stub",
        "stub-model",
        "https://provider.synthetic.invalid/v1",
    )
    route_orchestrator = TaskOrchestrator([stub_agent])
    return route_orchestrator


def test_slow_generation_does_not_change_acknowledged_interval() -> None:
    """Acknowledged interval must exclude slow stub generation time.

    Arranges an orchestrator whose stub generation boundary double sleeps up to
    the allowed limit, requests the initial decision receipt with
    ``decision_attempt`` set to ``initial``, and asserts the acknowledged
    ``admitted_first_at`` to ``receipt_acked_at`` interval on one monotonic
    clock excludes generation time.
    """
    route_orchestrator = _build_stub_orchestrator()
    slow_delay_seconds = 0.04

    def slow_stub_generation(stub_message_list: object) -> str:
        """Simulate one slow stub generation boundary double."""
        time_module.sleep(slow_delay_seconds)
        return "stub_generation_output"

    route_orchestrator.client.chat = slow_stub_generation  # type: ignore[method-assign]
    # RED for #1110: route_decision_receipt contract does not exist yet.
    receipt_request = route_orchestrator.request_route_decision_receipt  # type: ignore[attr-defined]
    initial_receipt = receipt_request(
        admission_id="admission_stub_001",
        decision_attempt="initial",
    )
    acknowledged_interval = (
        initial_receipt["receipt_acked_at"] - initial_receipt["admitted_first_at"]
    )
    assert acknowledged_interval < slow_delay_seconds


def test_failed_persistence_yields_no_success_receipt() -> None:
    """Failed persistence must yield no success receipt.

    Arranges a failing selection persistence boundary double, requests the
    route decision receipt, and asserts no success receipt with
    ``receipt_status`` equal to ``success`` is produced while the request stays
    in accepted-request accounting.
    """
    route_orchestrator = _build_stub_orchestrator()

    def failing_write_double(write_payload_text: object) -> object:
        """Simulate one failing selection persistence boundary double."""
        raise RuntimeError("stub_persistence_failure")

    route_orchestrator.client.chat = failing_write_double  # type: ignore[method-assign]
    # RED for #1110: route_decision_receipt contract does not exist yet.
    receipt_request = route_orchestrator.request_route_decision_receipt  # type: ignore[attr-defined]
    failed_receipt = receipt_request(
        admission_id="admission_stub_002",
        decision_attempt="initial",
    )
    assert failed_receipt["receipt_status"] != "success"
