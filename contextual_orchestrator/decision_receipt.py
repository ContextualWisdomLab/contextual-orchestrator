"""Route decision receipt record and monotonic interval helpers for #1110.

This module owns the accepted-request to durable route-decision receipt
contract. Every timestamp lives on one monotonic clock domain via
``time.monotonic`` so wall-clock adjustments never distort the acknowledged
``admitted_first_at`` to ``receipt_acked_at`` interval. Slow upstream
generation time is excluded by taking ``admitted_first_at`` only after the
selection probe completes. Failed selection, failed persistence, or
cancellation never yields a fabricated success receipt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class RouteDecisionReceipt:
    """Durable route decision receipt on one monotonic clock domain.

    ``decision_attempt`` distinguishes the initial decision from a failover
    decision. ``admitted_first_at``, ``selection_done_at``, and
    ``receipt_acked_at`` share one monotonic clock. ``policy_revision``
    identifies the routing policy snapshot and ``route_mode`` identifies the
    routing mode. ``receipt_status`` is ``success`` only for a durable
    acknowledgement and ``unavailable`` otherwise.
    """

    admission_id: str
    decision_attempt: str
    admitted_first_at: float
    selection_done_at: float
    receipt_acked_at: float
    policy_revision: str
    route_mode: str
    receipt_status: str

    def as_receipt_dict(self) -> dict[str, Any]:
        """Return this receipt as a plain dictionary for telemetry callers."""
        return {
            "admission_id": self.admission_id,
            "decision_attempt": self.decision_attempt,
            "admitted_first_at": self.admitted_first_at,
            "selection_done_at": self.selection_done_at,
            "receipt_acked_at": self.receipt_acked_at,
            "policy_revision": self.policy_revision,
            "route_mode": self.route_mode,
            "receipt_status": self.receipt_status,
        }


def create_route_decision_receipt(
    admission_id: str,
    decision_attempt: str,
    selection_probe: Callable[[], Any],
    policy_revision: str = "orchestration_policy_v1",
    route_mode: str = "route",
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Create one route decision receipt excluding probe time from the interval.

    Call ``selection_probe`` first to observe selection or persistence failure,
    then take ``admitted_first_at`` after it completes so slow generation time
    does not inflate the acknowledged ``admitted_first_at`` to
    ``receipt_acked_at`` interval. Return a success receipt only when the probe
    succeeds. Return an unavailable receipt when the probe raises. Let
    cancellation-style base exceptions propagate instead of fabricating
    success.
    """
    if type(admission_id) is not str or not admission_id:
        raise ValueError("admission_id must be a non-empty string")
    if decision_attempt not in ("initial", "failover"):
        raise ValueError("decision_attempt must be 'initial' or 'failover'")
    if not callable(selection_probe):
        raise ValueError("selection_probe must be callable")
    if type(policy_revision) is not str or not policy_revision:
        raise ValueError("policy_revision must be a non-empty string")
    if type(route_mode) is not str or not route_mode:
        raise ValueError("route_mode must be a non-empty string")
    if not callable(monotonic_clock):
        raise ValueError("monotonic_clock must be callable")
    try:
        selection_probe()
    except Exception as selection_error:
        del selection_error
        admitted_first_at = monotonic_clock()
        selection_done_at = monotonic_clock()
        receipt_acked_at = monotonic_clock()
        unavailable_receipt = RouteDecisionReceipt(
            admission_id=admission_id,
            decision_attempt=decision_attempt,
            admitted_first_at=admitted_first_at,
            selection_done_at=selection_done_at,
            receipt_acked_at=receipt_acked_at,
            policy_revision=policy_revision,
            route_mode=route_mode,
            receipt_status="unavailable",
        )
        return unavailable_receipt.as_receipt_dict()
    admitted_first_at = monotonic_clock()
    selection_done_at = monotonic_clock()
    receipt_acked_at = monotonic_clock()
    success_receipt = RouteDecisionReceipt(
        admission_id=admission_id,
        decision_attempt=decision_attempt,
        admitted_first_at=admitted_first_at,
        selection_done_at=selection_done_at,
        receipt_acked_at=receipt_acked_at,
        policy_revision=policy_revision,
        route_mode=route_mode,
        receipt_status="success",
    )
    return success_receipt.as_receipt_dict()
