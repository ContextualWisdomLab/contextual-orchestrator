"""Rejected observations must not change retained routing evidence."""

import pytest

from contextual_orchestrator.psychometric_routing import PsychometricRoutingEvidence


@pytest.mark.parametrize("context_id", ["first_context", "new_context"])
@pytest.mark.parametrize(
    "invalid_row",
    [[2], ["not_an_integer"], [None], [0.7], [1.7], [-0.7], [0.0], [1.0], ["1"]],
)
def test_rejected_row_preserves_evidence(context_id, invalid_row):
    """Invalid new and replacement rows preserve vectors, order, and revision."""
    evidence = PsychometricRoutingEvidence(max_contexts=2)
    evidence.observe_context_id("first_context", "agent_one", True, [1.0, 0.0])
    evidence.observe_context_id("second_context", "agent_one", False, [0.0, 1.0])
    before_records = evidence.records()
    before_contexts = list(evidence._contexts.items())
    before_vectors = dict(evidence._context_unit_vectors)
    before_revision = evidence._revision
    with pytest.raises((ValueError, TypeError)):
        evidence.observe_context_id(
            context_id, "agent_one", True, [-1.0, 0.0], invalid_row
        )
    assert evidence.records() == before_records
    assert list(evidence._contexts.items()) == before_contexts
    assert evidence._context_unit_vectors == before_vectors
    assert evidence._revision == before_revision


def test_integer_protocol_rows_preserve_binary_values():
    """Python and native integer scalar rows retain exact zero/one values."""
    import numpy as np

    evidence = PsychometricRoutingEvidence()
    evidence.observe_context_id(
        "integer_context", "agent_one", True, None, [0, 1, np.int64(0), np.int64(1)]
    )
    assert evidence.records()[0]["irt_row"] == [0, 1, 0, 1]
