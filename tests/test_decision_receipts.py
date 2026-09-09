"""Initial decisions must be acknowledged before any answer is generated."""

import http.client
import json
import threading
import sqlite3
import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import build_server, SecurityConfig


def test_http_route_persists_initial_decision(tmp_path, monkeypatch):
    """A real HTTP route retains one native-clock receipt before completion."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_one", "mock/worker")], state_db=tmp_path / "state.db"
    )
    original_chat = orchestrator.client.chat
    dispatch_records = []
    dispatch_ready = threading.Event()
    generation_allowed = threading.Event()
    dispatched_snapshots = []

    def inspect_committed_decision(*args, **kwargs):
        with sqlite3.connect(tmp_path / "state.db") as independent:
            rows = independent.execute(
                "SELECT payload FROM orchestration_records WHERE kind = 'initial_decision'"
            ).fetchall()
        assert len(rows) == 1
        dispatch_records.extend(rows)
        from contextual_orchestrator.decision_receipts import _CURRENT_DECISION
        dispatched_snapshots.append(_CURRENT_DECISION.get().snapshot())
        dispatch_ready.set()
        assert generation_allowed.wait(10)
        return original_chat(*args, **kwargs)

    monkeypatch.setattr(orchestrator.client, "chat", inspect_committed_decision)
    server = build_server(orchestrator, port=0, decision_receipts=True,
                          security=SecurityConfig(auth_token="test-token"))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = http.client.HTTPConnection(*server.server_address)
    try:
        connection.request(
            "POST", "/v1/chat/completions",
            json.dumps({"model": "orchestrator/auto", "mode": "route", "messages": [
                {"role": "user", "content": "hello"}
            ]}), {"Content-Type": "application/json", "Authorization": "Bearer test-token"},
        )
        assert dispatch_ready.wait(10)
        assert dispatched_snapshots[0]["status"] == "acknowledged"
        assert dispatched_snapshots[0]["durable_ack_elapsed_ns"] is not None
        # Hold generation after the ack: the final interval must remain exactly
        # the pre-generation native value, irrespective of the hold duration.
        assert not generation_allowed.is_set()
        generation_allowed.set()
        response = connection.getresponse()
        response.read()
        assert response.status == 200
        assert dispatch_records
        records = orchestrator._store.load("decision_receipt")
        assert len(records) == 1
        assert records[0]["status"] == "acknowledged"
        assert records[0]["selected_agent_ids"] == ["worker_one"]
        assert records[0]["selection_elapsed_ns"] <= records[0]["durable_ack_elapsed_ns"]
        assert records[0]["durable_ack_elapsed_ns"] == dispatched_snapshots[0]["durable_ack_elapsed_ns"]
        assert len(orchestrator._store.load("initial_decision")) == 1
    finally:
        generation_allowed.set()
        connection.close()
        server.shutdown()
        worker.join()
        server.server_close()
        orchestrator.close()


def test_measurement_requires_durable_store():
    """Opt-in cannot silently lose every missing-store denominator observation."""
    orchestrator = TaskOrchestrator([ModelAgent("worker_one", "mock/worker")])
    with pytest.raises(ValueError, match="durable state store"):
        build_server(orchestrator, port=0, decision_receipts=True)
    orchestrator.close()


def test_native_rejects_out_of_order_and_duplicate_ack():
    """Native transitions never manufacture missing elapsed times."""
    from contextual_orchestrator._decision_receipt import DecisionReceipt

    receipt = DecisionReceipt()
    with pytest.raises(ValueError):
        receipt.record_durable_ack()
    assert receipt.status == "accepted"
    assert receipt.durable_ack_elapsed_ns is None
    receipt.record_selection()
    receipt.record_durable_ack()
    before = receipt.durable_ack_elapsed_ns
    with pytest.raises(ValueError):
        receipt.record_durable_ack()
    assert receipt.durable_ack_elapsed_ns == before


def test_write_failure_has_no_ack_and_does_not_log_exception_contents(caplog):
    """Failed commits cannot become successful timing samples or leak detail."""
    from contextual_orchestrator.decision_receipts import DecisionMeasurement

    class FailedStore:
        def save(self, *args, **kwargs):
            raise RuntimeError("secret-canary-never-log")

    measurement = DecisionMeasurement(FailedStore())
    try:
        measurement.select(["worker_one"])
        snapshot = measurement.snapshot()
        assert snapshot["status"] == "write_failed"
        assert snapshot["durable_ack_elapsed_ns"] is None
        snapshot["selected_agent_ids"].append("untrusted_mutation")
        assert measurement.snapshot()["selected_agent_ids"] == ["worker_one"]
    finally:
        measurement.close()
    assert "secret-canary-never-log" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
