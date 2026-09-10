"""RED for issue #1106: owner must expose a released readiness/admission contract.

Currently fails: review_gateway has credential admission but no versioned
readiness contract, and build_review_orchestrator hardcodes the client budget.
"""

from contextual_orchestrator import review_gateway


def test_review_gateway_exposes_readiness_contract():
    assert hasattr(review_gateway, "REVIEW_READINESS_CONTRACT_VERSION")
