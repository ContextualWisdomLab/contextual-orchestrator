"""Answer reuse must not terminate a request containing later batch work."""

import pytest
import http.client
import json
import threading

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


@pytest.mark.parametrize("item_order", [
    ["cached", "cached"], ["cached", "fresh"], ["fresh", "cached"],
    ["cached", "failure"],
])
def test_http_local_batch_cache_aggregation(tmp_path, monkeypatch, item_order):
    """An actual admitted batch retains cache-only, mixed, and failed outcomes."""
    from contextual_orchestrator import ModelAgent, TaskOrchestrator
    from contextual_orchestrator.decision_receipts import export_decision_receipts
    from contextual_orchestrator.server import SecurityConfig, build_server

    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_one", "mock/worker")],
        state_db=tmp_path / "state.db", cache_ttl=60,
    )
    orchestrator.complete([{"role": "user", "content": "cached"}], mode="route")
    original_dispatch = orchestrator._dispatch
    def dispatch(messages, *args, **kwargs):
        if messages[-1]["content"] == "failure":
            raise ValueError("unit batch failure before selection")
        return original_dispatch(messages, *args, **kwargs)
    monkeypatch.setattr(orchestrator, "_dispatch", dispatch)
    finished = threading.Event()
    original_close = DecisionMeasurement.close
    def close_and_signal(measurement, reason="unfinished"):
        original_close(measurement, reason)
        finished.set()
    monkeypatch.setattr(DecisionMeasurement, "close", close_and_signal)
    server = build_server(orchestrator, port=0, decision_receipts=True,
                          security=SecurityConfig(auth_token="test-token"))
    server_worker = threading.Thread(target=server.serve_forever, daemon=True)
    server_worker.start()
    try:
        connection = http.client.HTTPConnection(*server.server_address)
        connection.request("POST", "/api/v1/batch_routing_jobs", json.dumps({
            "requests": [{"messages": [{"role": "user", "content": item}],
                          "mode": "route"} for item in item_order],
        }), {"Authorization": "Bearer test-token", "Content-Type": "application/json"})
        response = connection.getresponse()
        response.read()
        connection.close()
        assert finished.wait(5), "request receipt did not finalize"
        assert response.status == (400 if "failure" in item_order else 201)
        observations = export_decision_receipts(orchestrator._store)["observations"]
        assert len(observations) == 1
        observation = observations[0]
        expected_status = ("selection_failed" if "failure" in item_order else
                           "acknowledged" if "fresh" in item_order else "cache_hit")
        assert observation["status"] == expected_status
        assert (observation["durable_ack_elapsed_ns"] is not None) == ("fresh" in item_order)
        assert (observation["selection_elapsed_ns"] is not None) == ("fresh" in item_order)
    finally:
        server.shutdown()
        server_worker.join()
        server.server_close()
        orchestrator.close()
