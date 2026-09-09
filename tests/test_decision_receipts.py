"""Initial decisions must be acknowledged before any answer is generated."""

import http.client
import json
import threading

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import build_server


def test_http_route_persists_initial_decision(tmp_path):
    """A real HTTP route retains one native-clock receipt before completion."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_one", "mock/worker")], state_db=tmp_path / "state.db"
    )
    server = build_server(orchestrator, port=0, decision_receipts=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = http.client.HTTPConnection(*server.server_address)
    try:
        connection.request(
            "POST", "/v1/chat/completions",
            json.dumps({"model": "orchestrator/route", "messages": [
                {"role": "user", "content": "hello"}
            ]}), {"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
        assert response.status == 200
        records = orchestrator._store.load("decision_receipt")
        assert len(records) == 1
        assert records[0]["status"] == "acknowledged"
        assert records[0]["selected_agent_ids"] == ["worker_one"]
        assert records[0]["selection_elapsed_ns"] <= records[0]["durable_ack_elapsed_ns"]
        assert len(orchestrator._store.load("initial_decision")) == 1
    finally:
        connection.close()
        server.shutdown()
        worker.join()
        server.server_close()
        orchestrator.close()
