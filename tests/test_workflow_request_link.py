"""Trusted HTTP request identity survives durable workflow persistence."""

import http.client
import json
import threading

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server
from contextual_orchestrator.telemetry import current_request_id, request_identity


@pytest.mark.parametrize("mode,stream", [("route", False), ("conduct", False), ("route", True), ("write_failure", True)])
@pytest.mark.parametrize("measurement_enabled", [False, True])
def test_http_workflow_retains_origin_request(tmp_path, monkeypatch, mode, stream, measurement_enabled):
    """Provider-observed identity joins the stored run without caller identity trust."""
    orchestrator = TaskOrchestrator([ModelAgent("worker_one", "mock/worker")],
                                  state_db=tmp_path / "state.db")
    observed_ids = []
    if mode == "write_failure":
        original_save = orchestrator._store.save

        def fail_workflow_write(kind, *args, **kwargs):
            if kind == "workflow_run":
                raise RuntimeError("private-storage-failure")
            return original_save(kind, *args, **kwargs)

        monkeypatch.setattr(orchestrator._store, "save", fail_workflow_write)
    for method_name in ("chat", "stream_chat"):
        original_method = getattr(orchestrator.client, method_name)

        def observe(*args, _method=original_method, **kwargs):
            observed_ids.append(current_request_id())
            return _method(*args, **kwargs)

        monkeypatch.setattr(orchestrator.client, method_name, observe)
    server = build_server(orchestrator, port=0, decision_receipts=measurement_enabled,
                          security=SecurityConfig(auth_token="unit-token"))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=20)
    try:
        connection.request("POST", "/v1/chat/completions", json.dumps({
            "model": "orchestrator/auto", "mode": "route" if mode == "write_failure" else mode, "stream": stream,
            "messages": [{"role": "user", "content": "Explain addition briefly."}],
        }), {"Content-Type": "application/json", "Authorization": "Bearer unit-token",
             "X-Request-ID": "untrusted-client-id"})
        response = connection.getresponse()
        response_payload = response.read().decode()
        connection.close()
        server.shutdown()
        server.server_close()
        assert response.status == 200
        stored_runs = orchestrator._store.load("workflow_run")
        if mode == "write_failure":
            assert not stored_runs
            assert len(orchestrator._workflow_runs) == 1
            assert '"finish_reason": "error"' in response_payload
            assert "private-storage-failure" not in response_payload
            if measurement_enabled:
                from contextual_orchestrator.decision_receipts import export_decision_receipts
                receipts = export_decision_receipts(orchestrator._store)["observations"]
                assert len(receipts) == 1
                assert receipts[0]["status"] == "acknowledged"
            return
        assert len(stored_runs) == 1
        assert observed_ids and len(set(observed_ids)) == 1
        assert observed_ids[0] and observed_ids[0] != "untrusted-client-id"
        assert stored_runs[0]["request_id"] == observed_ids[0]
        if measurement_enabled:
            from contextual_orchestrator.decision_receipts import export_decision_receipts
            receipts = export_decision_receipts(orchestrator._store)["observations"]
            assert len(receipts) == 1
            assert receipts[0]["request_id"] == stored_runs[0]["request_id"]
        run_id = stored_runs[0]["workflow_run_id"]
        orchestrator.close()
        restored = TaskOrchestrator([ModelAgent("worker_one", "mock/worker")],
                                   state_db=tmp_path / "state.db")
        try:
            assert restored.get_workflow_run(run_id)["request_id"] == observed_ids[0]
        finally:
            restored.close()
    finally:
        connection.close()
        server.shutdown()
        worker.join()
        server.server_close()
        orchestrator.close()


def test_workflow_update_preserves_original_request_identity():
    """Later request contexts cannot claim an existing run or a non-HTTP run."""
    orchestrator = TaskOrchestrator([ModelAgent("worker_one", "mock/worker")])
    try:
        for origin_http in (False, True):
            run_id = f"run_{origin_http}"
            record = {"workflow_run_id": run_id, "trace": []}
            if origin_http:
                with request_identity() as origin_id:
                    orchestrator._replace_workflow_run(record)
            else:
                origin_id = None
                orchestrator._replace_workflow_run(record)
            with request_identity():
                replacement = {"workflow_run_id": run_id, "trace": []}
                orchestrator._replace_workflow_run(replacement)
            assert replacement.get("request_id") == origin_id
    finally:
        orchestrator.close()


def test_http_cache_hit_keeps_distinct_outcome_identity(tmp_path):
    """A reused answer creates a cache-hit outcome, not a reassigned execution."""
    from contextual_orchestrator.decision_receipts import export_decision_receipts

    orchestrator = TaskOrchestrator([ModelAgent("worker_one", "mock/worker")],
                                  state_db=tmp_path / "state.db", cache_ttl=60)
    server = build_server(orchestrator, port=0, decision_receipts=True,
                          security=SecurityConfig(auth_token="unit-token"))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for _ in range(2):
            connection = http.client.HTTPConnection(*server.server_address, timeout=20)
            try:
                connection.request("POST", "/v1/chat/completions", json.dumps({
                    "model": "orchestrator/auto", "mode": "route",
                    "messages": [{"role": "user", "content": "Explain addition briefly."}],
                }), {"Content-Type": "application/json", "Authorization": "Bearer unit-token"})
                response = connection.getresponse()
                response.read()
                assert response.status == 200
            finally:
                connection.close()
        server.shutdown()
        server.server_close()
        stored_runs = orchestrator._store.load("workflow_run")
        receipts = export_decision_receipts(orchestrator._store)["observations"]
        assert [record["cache_status"] for record in stored_runs] == ["miss", "hit"]
        assert len({record["workflow_run_id"] for record in stored_runs}) == 2
        assert len({record["request_id"] for record in stored_runs}) == 2
        assert {record["request_id"] for record in stored_runs} == {
            receipt["request_id"] for receipt in receipts
        }
        assert sorted(receipt["status"] for receipt in receipts) == ["acknowledged", "cache_hit"]
    finally:
        server.shutdown()
        worker.join()
        server.server_close()
        orchestrator.close()
