"""RED for issue #1114: export bounded authorized request-outcome associations.

The analytics snapshot currently carries KPIs/drivers but no section connecting
a retained admission cohort to workflow IDs and batch job/item IDs. This test
requires that section key. Currently fails by design.
"""

from contextual_orchestrator import orchestrator


def test_analytics_snapshot_carries_outcome_associations():
    assert hasattr(orchestrator, "REQUEST_OUTCOME_ASSOCIATIONS_FIELD")
    assert orchestrator.REQUEST_OUTCOME_ASSOCIATIONS_FIELD == "request_outcome_associations"
