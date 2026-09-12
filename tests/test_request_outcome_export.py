"""Service-admin exports preserve admitted cohorts without exposing content."""

import threading
import pytest

from contextual_orchestrator import CostRoutingCoordinator, ModelAgent, TaskOrchestrator
from contextual_orchestrator.batch_routing import PgLlmBatchBackend
from contextual_orchestrator.server import SecurityConfig, build_server
from test_batch_routing import _FakeBatchApiClient
from test_cost_review_server import _request


@pytest.fixture
def export_server(tmp_path):
    """Run the actual HTTP adapter against isolated persistent state."""
    orchestrator = TaskOrchestrator([ModelAgent("worker_one", "mock/worker")], state_db=tmp_path / "state.db")
    server = build_server(orchestrator, port=0, security=SecurityConfig(
        bearer_verifier=lambda token, scope: token == "admin-token" and scope == "admin"))
    worker_thread = threading.Thread(target=server.serve_forever, daemon=True)
    worker_thread.start()
    try:
        yield orchestrator, f"http://127.0.0.1:{server.server_address[1]}/api/v1/request_outcome_exports"
    finally:
        server.shutdown()
        worker_thread.join()
        server.server_close()
        orchestrator.close()


@pytest.mark.parametrize("token", [None, "inference-token", "trace-token", "operator-token"])
def test_export_denies_non_admin_before_query(export_server, monkeypatch, token):
    """A wrong role must not read global observations before rejection."""
    orchestrator, export_url = export_server
    queries = []
    original = orchestrator._store.export_request_outcomes

    def observe_query(**kwargs):
        queries.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(orchestrator._store, "export_request_outcomes", observe_query)
    status, _ = _request("GET", export_url, token)
    assert status == 401
    assert not queries


@pytest.mark.parametrize("query", ["page_size=0", "page_size=201", "page_size=true",
                                  "after_sequence=-1", "after_sequence=1",
                                  "high_water_sequence=999999999999999999999999",
                                  "page_size=1&page_size=2", "owner_id=spoofed",
                                  "unknown=", "page_size=", "page_size=1&page_size="])
def test_export_rejects_invalid_cursor(export_server, query):
    """Invalid or unbounded cursor requests cannot become a full-ledger read."""
    _, export_url = export_server
    status, _ = _request("GET", export_url + "?" + query, "admin-token")
    assert status == 400


def test_export_freezes_late_link_and_rejects_projection_commit_failure(export_server):
    """Late completion stays outside the cutoff; projection failure rolls source back."""
    orchestrator, export_url = export_server
    store = orchestrator._store
    store.save("accepted_request", "request_one", {"request_id": "request_one"}, durable=True)
    status, initial = _request("GET", export_url, "admin-token")
    assert status == 200
    record = {"workflow_run_id": "workflow_one", "request_id": "request_one", "cache_status": "hit"}
    store._conn.execute("CREATE TRIGGER reject_link BEFORE INSERT ON orchestration_records "
                        "WHEN NEW.kind = 'workflow_request_link' BEGIN SELECT RAISE(ABORT, 'unit-failure'); END")
    with pytest.raises(Exception, match="unit-failure"):
        store.save("workflow_run", "workflow_one", record)
    assert not store.load("workflow_run")
    assert not store.load("workflow_request_link")
    store._conn.execute("DROP TRIGGER reject_link")
    store.save("workflow_run", "workflow_one", record)
    store.save("workflow_run", "workflow_one", record)
    assert len(store.load("workflow_request_link")) == 1
    status, frozen = _request("GET", export_url + f"?high_water_sequence={initial['high_water_sequence']}", "admin-token")
    assert status == 200
    assert frozen["observations"] == initial["observations"]
    status, current = _request("GET", export_url, "admin-token")
    assert current["observations"][0]["workflow_outcomes"][0]["cache_status"] == "hit"
    assert len(current["observations"][0]["workflow_outcomes"]) == 1


def test_projection_rejects_origin_reassignment(export_server):
    """A repeated source write cannot create two origins for one workflow."""
    orchestrator, _ = export_server
    store = orchestrator._store
    record = {"workflow_run_id": "workflow_one", "request_id": "request_one"}
    store.save("workflow_run", "workflow_one", record)
    with pytest.raises(ValueError, match="origin"):
        store.save("workflow_run", "workflow_one", {**record, "request_id": "request_two"})
    assert store.load("workflow_run")[0]["request_id"] == "request_one"


def test_http_export_retains_fixed_cohort_links_after_restart(tmp_path):
    """A missing export loses persisted workflow/batch joins and failure rows."""
    state_path = tmp_path / "state.db"
    agents = [ModelAgent("worker_one", "mock/worker")]
    security = SecurityConfig(admin_token="admin-token", inference_token="inference-token")
    orchestrator = TaskOrchestrator(agents, state_db=state_path)
    coordinator = CostRoutingCoordinator(orchestrator, batch_backend=PgLlmBatchBackend(_FakeBatchApiClient()))
    server = build_server(orchestrator, port=0, security=security,
                          coordinator=coordinator, decision_receipts=True)
    worker_thread = threading.Thread(target=server.serve_forever, daemon=True)
    worker_thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, _ = _request("POST", base_url + "/v1/chat/completions", "inference-token", {
            "model": "orchestrator/auto", "mode": "route",
            "messages": [{"role": "user", "content": "private-prompt-marker"}],
        })
        assert status == 200
        status, submitted = _request("POST", base_url + "/api/v1/batch_routing_jobs", "inference-token", {
            "requests": [{"custom_id": "item_one", "model": "mock/worker",
                          "messages": [{"role": "user", "content": "private-batch-marker"}]}],
        })
        assert status == 201
        for _ in range(security.max_concurrent_runs):
            security.acquire_run_slot()
        try:
            status, _ = _request("POST", base_url + "/v1/chat/completions", "inference-token", {
                "messages": [{"role": "user", "content": "capacity failure"}],
            })
            assert status == 503
        finally:
            for _ in range(security.max_concurrent_runs):
                security.release_run_slot()
    finally:
        server.shutdown()
        worker_thread.join()
        server.server_close()
        orchestrator.close()

    restored = TaskOrchestrator(agents, state_db=state_path)
    server = build_server(restored, port=0, security=security, decision_receipts=True)
    worker_thread = threading.Thread(target=server.serve_forever, daemon=True)
    worker_thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    export_url = base_url + "/api/v1/request_outcome_exports"
    try:
        denied_status, _ = _request("GET", export_url, "inference-token")
        assert denied_status == 401
        status, first = _request("GET", export_url + "?page_size=1", "admin-token")
        assert status == 200, first
        assert first["scope"] == "service_admin_retained_admissions"
        assert first["measurement_complete"] is False
        assert len(first["observations"]) == 1
        first_row = first["observations"][0]
        assert len(first_row["workflow_outcomes"]) == 1
        assert first_row["batch_associations"] == []
        prior_run = restored._store.load("workflow_run")[0]
        restored._store.save("workflow_run", prior_run["workflow_run_id"], prior_run)
        replay_status, replay = _request(
            "GET", export_url + f"?page_size=1&high_water_sequence={first['high_water_sequence']}",
            "admin-token")
        assert replay_status == 200
        assert replay["observations"] == first["observations"]
        status, _ = _request("POST", base_url + "/v1/chat/completions", "inference-token", {})
        assert status == 400
        query = (f"?page_size=10&after_sequence={first['next_after_sequence']}"
                 f"&high_water_sequence={first['high_water_sequence']}")
        status, remaining = _request("GET", export_url + query, "admin-token")
        assert status == 200
        rows = [first_row, *remaining["observations"]]
        assert len(rows) == 3
        assert len({row["request_id"] for row in rows}) == 3
        assert rows[1]["batch_associations"] == [{"batch_job_id": submitted["job_id"],
                                                  "custom_ids": ["item_one"]}]
        assert rows[2]["workflow_outcomes"] == []
        assert rows[2]["batch_associations"] == []
        assert rows[2]["decision_status"] == "capacity_rejected"
        assert remaining["next_after_sequence"] is None
        exported = str(rows)
        for private_field in ("private-prompt-marker", "private-batch-marker", "owner_id",
                              "recovery_descriptor", "messages", "answer", "provider_config"):
            assert private_field not in exported
    finally:
        server.shutdown()
        worker_thread.join()
        server.server_close()
        restored.close()


def test_export_rejects_malformed_private_association(export_server):
    """Nested private data cannot masquerade as an exported identifier."""
    orchestrator, export_url = export_server
    store = orchestrator._store
    store.save("accepted_request", "request_one", {"request_id": "request_one"}, durable=True)
    store.save("batch_request_link", "batch_one", {"request_id": "request_one", "batch_job_id": "batch_one",
                                                 "custom_ids": [{"private_payload": "do not disclose"}]}, durable=True)
    status, result = _request("GET", export_url, "admin-token")
    assert status == 200
    assert result["observations"][0]["batch_associations"] == []
    assert result["observations"][0]["invalid_association_count"] == 1
    assert "do not disclose" not in str(result)


def test_export_rejects_admission_key_mismatch(export_server):
    """Malformed admission identity must not join another request's records."""
    orchestrator, export_url = export_server
    store = orchestrator._store
    store._conn.execute("INSERT INTO orchestration_records(kind,key,payload) VALUES ('accepted_request','wrong',?)",
                        ('{"request_id":"different"}',))
    store._conn.commit()
    status, result = _request("GET", export_url, "admin-token")
    assert status == 200
    assert result["observations"][0]["request_id"] is None
    assert result["observations"][0]["link_status"] == "identity_unavailable"


def test_export_cursor_survives_unrelated_pruning(export_server):
    """Deleting the latest unrelated row must not invalidate an issued cutoff."""
    orchestrator, _ = export_server
    store = orchestrator._store
    store.save("accepted_request", "request_one", {"request_id": "request_one"}, durable=True)
    store.save("psychometric_observation", "observation_one", {})
    initial = store.export_request_outcomes()
    store.prune_keyed("psychometric_observation", set())
    replay = store.export_request_outcomes(high_water_sequence=initial["high_water_sequence"])
    assert replay["observations"] == initial["observations"]


def test_export_discloses_link_caps_and_uses_query_indexes(export_server):
    """A bounded fanout is disclosed; identity joins do not scan the journal."""
    orchestrator, _ = export_server
    store = orchestrator._store
    store.save("accepted_request", "request_one", {"request_id": "request_one"}, durable=True)
    for item_index in range(18):
        workflow_id = f"workflow_{item_index}"
        record = {"request_id": "request_one", "workflow_run_id": workflow_id}
        for _ in range(3):
            store.save("workflow_run", workflow_id, record)
    store.save("batch_request_link", "batch_one", {"request_id": "request_one", "batch_job_id": "batch_one",
               "custom_ids": [f"item_{item_index}" for item_index in range(101)]}, durable=True)
    row = store.export_request_outcomes()["observations"][0]
    assert len(row["workflow_outcomes"]) == 16
    assert len(row["batch_associations"][0]["custom_ids"]) == 100
    assert row["links_truncated"] is True
    assert len(store.load("workflow_request_link")) == 18
    query_plan = store._conn.execute(
        "EXPLAIN QUERY PLAN SELECT payload FROM orchestration_records "
        "WHERE kind IN ('workflow_run', 'batch_request_link') AND json_valid(payload) "
        "AND kind = ? AND json_extract(payload, '$.request_id') = ? "
        "AND seq <= ? ORDER BY seq LIMIT 17", ("batch_request_link", "request_one", 10000),
    ).fetchall()
    assert any("orchestration_records_request_link_seq" in row[-1] for row in query_plan)


@pytest.mark.parametrize("record_kind,payload", [
    ("decision_receipt", '{"request_id":"request_one","status":[]}'),
    ("decision_receipt", '{"request_id":"other","status":"acknowledged"}'),
    ("workflow_request_link", '[]'),
    ("workflow_request_link", '{"request_id":"other","workflow_run_id":"workflow_one","cache_status":"hit","source_record_sequence":1}'),
    ("workflow_request_link", '{"request_id":"request_one","workflow_run_id":"workflow_one","cache_status":{},"source_record_sequence":1}'),
])
def test_export_keeps_admission_when_retained_metadata_invalid(export_server, record_kind, payload):
    """Malformed persisted metadata stays unresolved without leaking or crashing."""
    orchestrator, export_url = export_server
    store = orchestrator._store
    store.save("accepted_request", "request_one", {"request_id": "request_one"}, durable=True)
    store._conn.execute("INSERT INTO orchestration_records(kind,key,payload) VALUES (?,?,?)",
                        (record_kind, "request_one", payload))
    store._conn.commit()
    status, result = _request("GET", export_url, "admin-token")
    assert status == 200
    assert len(result["observations"]) == 1
    row = result["observations"][0]
    assert row["workflow_outcomes"] == []
    assert row["invalid_association_count"] == 1


def test_export_index_migration_does_not_invent_old_link_history(tmp_path):
    """Reopening pre-projection state indexes it without fabricating old events."""
    from contextual_orchestrator.orchestrator import _StateStore
    state_path = tmp_path / "legacy.db"
    store = _StateStore(str(state_path))
    store.save("accepted_request", "request_one", {"request_id": "request_one"}, durable=True)
    store._conn.execute("INSERT INTO orchestration_records(kind,key,payload) VALUES ('workflow_run','old_run',?)",
                        ('{"workflow_run_id":"old_run","request_id":"request_one"}',))
    store._conn.execute("DROP INDEX orchestration_records_request_link_seq")
    store._conn.execute("DROP INDEX orchestration_records_workflow_origin")
    store._conn.commit()
    store.close()
    restored = _StateStore(str(state_path))
    try:
        row = restored.export_request_outcomes()["observations"][0]
        assert row["link_status"] == "unmatched"
        assert not row["workflow_outcomes"]
        assert not restored.load("workflow_request_link")
        assert restored.load("workflow_run")[0]["workflow_run_id"] == "old_run"
    finally:
        restored.close()


@pytest.mark.parametrize("parameters", [{"page_size": True}, {"after_sequence": True},
                                         {"high_water_sequence": False}])
def test_store_export_rejects_boolean_cursor(export_server, parameters):
    """Python bool must not be interpreted as a valid integer cursor."""
    orchestrator, _ = export_server
    with pytest.raises(ValueError):
        orchestrator._store.export_request_outcomes(**parameters)


def test_export_published_query_contract_bounds_page_size():
    """Generated clients must discover the admin export and its bounded query."""
    from contextual_orchestrator.api_contract import OPENAPI_SPEC
    from jsonschema import validate, ValidationError
    operation = OPENAPI_SPEC["paths"]["/api/v1/request_outcome_exports"]["get"]
    assert operation["security"] == [{"admin_bearer_auth": []}]
    page_schema = next(item["schema"] for item in operation["parameters"] if item["name"] == "page_size")
    validate(200, page_schema)
    with pytest.raises(ValidationError):
        validate(201, page_schema)


def test_export_requires_durable_authorization_audit(export_server, monkeypatch):
    """An audit failure must deny even a valid service-admin export."""
    orchestrator, export_url = export_server
    queries = []

    def reject_audit(**kwargs):
        raise RuntimeError("private-audit-error")

    def observe_query(**kwargs):
        queries.append(kwargs)
        return {}

    monkeypatch.setattr(orchestrator, "record_authorization_decision", reject_audit)
    monkeypatch.setattr(orchestrator._store, "export_request_outcomes", observe_query)
    status, result = _request("GET", export_url, "admin-token")
    assert status == 503
    assert not queries
    assert "private-audit-error" not in str(result)


def test_malformed_retained_link_survives_index_migration(tmp_path):
    """Invalid metadata remains countable without preventing startup or valid writes."""
    import sqlite3
    from contextual_orchestrator.orchestrator import _StateStore

    state_path = tmp_path / "malformed.db"
    with sqlite3.connect(state_path) as connection:
        connection.execute(_StateStore._CREATE_RECORDS_SQL)
        connection.execute(_StateStore._INSERT_SQL,
                           ("accepted_request", "request_one", '{"request_id":"request_one"}'))
        connection.execute(_StateStore._INSERT_SQL,
                           ("workflow_request_link", "request_one", '{broken'))
    store = _StateStore(str(state_path))
    try:
        store.save("workflow_run", "workflow_one", {
            "request_id": "request_one", "workflow_run_id": "workflow_one", "cache_status": "miss",
        })
        row, = store.export_request_outcomes()["observations"]
        assert row["invalid_association_count"] == 1
        assert row["workflow_outcomes"][0]["workflow_run_id"] == "workflow_one"
        assert store._conn.execute("SELECT count(*) FROM orchestration_records WHERE payload = ?",
                                   ('{broken',)).fetchone()[0] == 1
    finally:
        store.close()
