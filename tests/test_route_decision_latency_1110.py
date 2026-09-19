"""RED for issue #1110: accepted-request to durable route-decision latency.

route_once currently times _invoke end-to-end, so trace latency_ms includes
upstream generation and cannot supply routing_decision_latency_p95. This test
requires a decision-only interval on the trace row, distinct from generation.
Currently fails by design.
"""

from contextual_orchestrator import orchestrator


def test_route_trace_carries_decision_only_latency():
    assert hasattr(orchestrator, "ROUTE_DECISION_LATENCY_FIELD")
    assert orchestrator.ROUTE_DECISION_LATENCY_FIELD == "decision_latency_ms"
