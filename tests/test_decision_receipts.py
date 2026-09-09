"""Initial decisions must be acknowledged before any answer is generated."""

import http.client
import json
import threading
import sqlite3
import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import build_server, SecurityConfig


@pytest.mark.parametrize("endpoint,stream", [
    ("/v1/chat/completions", False), ("/v1/chat/completions", True),
    ("/v1/responses", True),
])
def test_http_route_persists_initial_decision(tmp_path, monkeypatch, endpoint, stream):
    """A real HTTP route retains one native-clock receipt before completion."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_one", "mock/worker")], state_db=tmp_path / "state.db"
    )
    dispatch_records = []
    dispatch_ready = threading.Event()
    generation_allowed = threading.Event()
    dispatched_snapshots = []

    def inspect_committed_decision(original_call, *args, **kwargs):
        with sqlite3.connect(tmp_path / "state.db") as independent:
            rows = independent.execute(
                "SELECT payload FROM orchestration_records WHERE kind = 'initial_decision'"
            ).fetchall()
            assert independent.execute(
                "SELECT COUNT(*) FROM orchestration_records WHERE kind = 'accepted_request'"
            ).fetchone()[0] == 1
        assert len(rows) == 1
        dispatch_records.extend(rows)
        from contextual_orchestrator.decision_receipts import _CURRENT_DECISION
        dispatched_snapshots.append(_CURRENT_DECISION.get().snapshot())
        dispatch_ready.set()
        assert generation_allowed.wait(10)
        return original_call(*args, **kwargs)

    for method_name in ("chat", "stream_chat"):
        original_call = getattr(orchestrator.client, method_name)
        monkeypatch.setattr(orchestrator.client, method_name,
                            lambda *args, _call=original_call, **kwargs:
                            inspect_committed_decision(_call, *args, **kwargs))
    server = build_server(orchestrator, port=0, decision_receipts=True,
                          security=SecurityConfig(auth_token="test-token"))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = http.client.HTTPConnection(*server.server_address)
    try:
        body = {"model": "orchestrator/auto", "mode": "route", "stream": stream,
                "messages": [{"role": "user", "content": "hello"}]}
        if endpoint == "/v1/responses":
            body = {"model": "orchestrator/auto", "stream": True, "input": "hello"}
        connection.request(
            "POST", endpoint, json.dumps(body),
            {"Content-Type": "application/json", "Authorization": "Bearer test-token"},
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
            if args[0] == "initial_decision":
                raise RuntimeError("secret-canary-never-log")

    measurement = DecisionMeasurement(FailedStore())
    try:
        measurement.select(["worker_one"], "route")
        snapshot = measurement.snapshot()
        assert snapshot["status"] == "write_failed"
        assert snapshot["durable_ack_elapsed_ns"] is None
        snapshot["selected_agent_ids"].append("untrusted_mutation")
        assert measurement.snapshot()["selected_agent_ids"] == ["worker_one"]
    finally:
        measurement.close()
    assert "secret-canary-never-log" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


def test_admission_write_failure_rejects_before_dispatch_and_recovers(tmp_path, monkeypatch):
    """A failed ingress receipt returns safe 503 and does not poison the next context."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_one", "mock/worker")], state_db=tmp_path / "state.db"
    )
    original_save = orchestrator._store.save
    original_chat = orchestrator.client.chat
    failed_once = []
    dispatched = []

    def fail_first_admission(kind, *args, **kwargs):
        if kind == "accepted_request" and not failed_once:
            failed_once.append(True)
            raise RuntimeError("never-disclose-storage-secret")
        return original_save(kind, *args, **kwargs)

    def record_dispatch(*args, **kwargs):
        dispatched.append(True)
        return original_chat(*args, **kwargs)

    monkeypatch.setattr(orchestrator._store, "save", fail_first_admission)
    monkeypatch.setattr(orchestrator.client, "chat", record_dispatch)
    server = build_server(orchestrator, port=0, decision_receipts=True,
                          security=SecurityConfig(auth_token="test-token"))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = http.client.HTTPConnection(*server.server_address)
    try:
        for expected_status in (503, 200):
            connection.request("POST", "/v1/chat/completions", json.dumps({
                "model": "orchestrator/auto", "mode": "route",
                "messages": [{"role": "user", "content": "hello"}],
            }), {"Content-Type": "application/json", "Authorization": "Bearer test-token"})
            response = connection.getresponse()
            payload = response.read().decode()
            assert response.status == expected_status
            assert "never-disclose-storage-secret" not in payload
            if expected_status == 503:
                assert not dispatched
                assert '"measurement_complete": false' in payload
        assert len(orchestrator._store.load("accepted_request")) == 1
        assert len(orchestrator._store.load("decision_receipt")) == 1
    finally:
        connection.close()
        server.shutdown()
        worker.join()
        server.server_close()
        orchestrator.close()


def test_export_retains_accepted_request_without_finalization(tmp_path):
    """Crash-like missing finalization stays an unfinished denominator row."""
    from contextual_orchestrator.decision_receipts import export_decision_receipts
    from contextual_orchestrator.orchestrator import _StateStore

    store = _StateStore(tmp_path / "state.db")
    try:
        store.save("accepted_request", None, {
            "request_id": "accepted_only", "status": "accepted",
            "selection_elapsed_ns": None, "durable_ack_elapsed_ns": None,
        }, durable=True)
        exported = export_decision_receipts(store)
        assert exported["measurement_complete"] is False
        assert exported["reconciliation_required"] is True
        assert exported["observations"][0]["request_id"] == "accepted_only"
        assert exported["observations"][0]["status"] == "unfinished"
        assert exported["observations"][0]["durable_ack_elapsed_ns"] is None
    finally:
        store.close()


@pytest.mark.parametrize("invalid_capacity", [False, True])
def test_race_receipt_retains_candidate_set_not_winner(tmp_path, monkeypatch, invalid_capacity):
    """Real race workers share one clock; rejected races cannot acknowledge selection."""
    from contextual_orchestrator.decision_receipts import DecisionMeasurement
    from contextual_orchestrator.orchestrator import MAX_LOCAL_CONCURRENCY

    contract = {
        "contract_id": "test_contract", "model_revision": "test_revision",
        "reasoning_effort_profile": "worker_medium", "capability_set": ["text"],
        "structured_output_contract": "openai_response_v1", "accuracy_class": "full_precision",
        "data_residency_policy": "test_region", "retention_policy": "zero_retention",
        "context_limit": 128000, "pricing_evidence_id": "test_price_evidence",
        "hedge_eligible": True, "cancellation_supported": False,
        "execution_policy": "immediate_race",
    }
    agents = [ModelAgent(f"worker_{index}", "mock/worker", group_name="shared_group",
                        endpoint_equivalence=contract)
              for index in range(2)]
    orchestrator = TaskOrchestrator(agents, state_db=tmp_path / "state.db")
    measurement = DecisionMeasurement(orchestrator._store)
    try:
        if invalid_capacity:
            monkeypatch.setattr(orchestrator, "_equivalent_race_members",
                                lambda *args, **kwargs: [agents[0]] * (MAX_LOCAL_CONCURRENCY + 1))
            with pytest.raises(ValueError, match="concurrency capacity"):
                orchestrator._invoke(agents[0], [{"role": "user", "content": "hello"}],
                                     text="hello", role="worker")
            assert measurement.receipt.status == "accepted"
            assert not orchestrator._store.load("initial_decision")
        else:
            orchestrator._invoke(agents[0], [{"role": "user", "content": "hello"}],
                                 text="hello", role="worker")
            snapshot = measurement.snapshot()
            assert snapshot["status"] == "acknowledged"
            assert set(snapshot["selected_agent_ids"]) == {"worker_0", "worker_1"}
            assert len(orchestrator._store.load("initial_decision")) == 1
    finally:
        measurement.close()
        orchestrator.close()
