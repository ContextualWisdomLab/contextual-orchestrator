"""Answer reuse must not terminate a request containing later batch work."""

import pytest

from contextual_orchestrator.decision_receipts import (
    DecisionMeasurement,
    record_answer_cache_hit,
)


class RecordingStore:
    """Keep receipt writes observable without a provider or storage dependency."""

    def __init__(self):
        self.records = []

    def save(self, record_kind, record_key, payload, *, durable=False):
        self.records.append((record_kind, dict(payload)))


@pytest.mark.parametrize("operations", ["cache_cache", "cache_select", "select_cache"])
def test_request_cache_observations_preserve_first_selection(operations):
    """Mixed batch order cannot erase selection or reject an otherwise valid item."""
    store = RecordingStore()
    measurement = DecisionMeasurement(store)
    try:
        for operation in operations.split("_"):
            if operation == "cache":
                record_answer_cache_hit()
            else:
                measurement.select(["worker_one"], "route")
        snapshot = measurement.snapshot()
        if "select" in operations:
            assert snapshot["status"] == "acknowledged"
            assert snapshot["selection_elapsed_ns"] is not None
            assert snapshot["durable_ack_elapsed_ns"] is not None
        else:
            assert snapshot["status"] == "accepted"
    finally:
        measurement.close()
    final_snapshot = store.records[-1][1]
    assert final_snapshot["status"] == (
        "acknowledged" if "select" in operations else "cache_hit"
    )
    if "select" not in operations:
        assert final_snapshot["selection_elapsed_ns"] is None
        assert final_snapshot["durable_ack_elapsed_ns"] is None


@pytest.mark.parametrize("failure_reason", ["selection_failed", "cancelled"])
def test_cached_item_does_not_hide_later_request_failure(failure_reason):
    """Failure after an answer-cache item remains a failed admitted request."""
    store = RecordingStore()
    measurement = DecisionMeasurement(store)
    record_answer_cache_hit()
    measurement.close(failure_reason)
    assert store.records[-1][1]["status"] == failure_reason


def test_cache_observation_preserves_existing_write_failure():
    """A later cached item cannot overwrite a durable selection-write failure."""
    store = RecordingStore()
    measurement = DecisionMeasurement(store)
    try:
        measurement.receipt.record_failure("write_failed")
        record_answer_cache_hit()
    finally:
        measurement.close()
    assert store.records[-1][1]["status"] == "write_failed"
