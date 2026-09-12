"""Retained-cohort projection preserves native timing provenance, not KPI proof."""

from contextual_orchestrator.orchestrator import _StateStore
import pytest


@pytest.mark.parametrize("field_name,bad_value", [
    ("selection_elapsed_ns", -1), ("durable_ack_elapsed_ns", True),
    ("first_provider_elapsed_ns", 2**64),
    ("measurement_unit", "private-text"), ("metric_scope", []),
    ("policy_snapshot_hash", "private-text"), ("admission_boundary", "unknown"),
])
def test_invalid_measurement_metadata_is_null(tmp_path, field_name, bad_value):
    """Invalid retained values remain unavailable and cannot leak arbitrary text."""
    store = _StateStore(str(tmp_path / "metadata.db"))
    try:
        store.save("accepted_request", "request_one", {
            "request_id": "request_one", field_name: bad_value,
        }, durable=True)
        observation = store.export_request_outcomes()["observations"][0]
        assert observation[field_name] is None
    finally:
        store.close()


def test_invalid_initial_identity_is_counted(tmp_path):
    """Corrupt phase identity is distinct from an ordinary unfinished request."""
    store = _StateStore(str(tmp_path / "identity.db"))
    try:
        store.save("accepted_request", "request_one", {"request_id": "request_one"}, durable=True)
        store._conn.execute(
            "INSERT INTO orchestration_records(kind,key,payload) VALUES (?,?,?)",
            ("initial_decision", "request_one", '{"request_id":"other","selection_elapsed_ns":12}'),
        )
        store._conn.commit()
        observation = store.export_request_outcomes()["observations"][0]
        assert observation["invalid_association_count"] == 1
        assert observation["decision_status"] == "unfinished"
        assert observation["selection_elapsed_ns"] is None
    finally:
        store.close()


@pytest.mark.parametrize("receipt_status,selection_ns,ack_ns", [
    ("write_failed", 10, 20), ("cache_hit", None, 20),
    ("unknown_status", 10, 20), ("acknowledged", 20, 10),
    ("acknowledged", -1, 20), ("acknowledged", True, 20),
    ("acknowledged", 10, True), ("acknowledged", 10, -1),
    ("acknowledged", 10, 2**64),
])
def test_invalid_acknowledgement_is_not_a_duration(tmp_path, receipt_status, selection_ns, ack_ns):
    """Corrupt retained metadata cannot create successful measurement evidence."""
    store = _StateStore(str(tmp_path / "invalid.db"))
    try:
        store.save("accepted_request", "request_one", {"request_id": "request_one"}, durable=True)
        store.save("decision_receipt", "request_one", {
            "request_id": "request_one", "status": receipt_status,
            "selection_elapsed_ns": selection_ns, "durable_ack_elapsed_ns": ack_ns,
        }, durable=True)
        observation = store.export_request_outcomes()["observations"][0]
        assert observation["durable_ack_elapsed_ns"] is None
        assert observation["decision_latency_ms"] is None
        assert observation["invalid_association_count"] >= 1
    finally:
        store.close()


@pytest.mark.parametrize("phase_status,selection_ns,ack_ns", [
    ("cache_hit", 12, None), ("selected", None, None),
    ("selected", True, None), ("selected", -1, None),
    ("selected", 2**64, None), ("selected", 12, 20),
])
def test_invalid_initial_phase_is_counted(tmp_path, phase_status, selection_ns, ack_ns):
    """Only a selected, not-yet-acknowledged phase establishes a missing receipt."""
    store = _StateStore(str(tmp_path / "initial_phase.db"))
    try:
        store.save("accepted_request", "request_one", {"request_id": "request_one"}, durable=True)
        store.save("initial_decision", "request_one", {
            "request_id": "request_one", "status": phase_status,
            "selection_elapsed_ns": selection_ns, "durable_ack_elapsed_ns": ack_ns,
        }, durable=True)
        observation = store.export_request_outcomes()["observations"][0]
        assert observation["invalid_association_count"] == 1
        assert observation["decision_status"] == "unfinished"
        assert observation["selection_elapsed_ns"] is None
        assert observation["durable_ack_elapsed_ns"] is None
    finally:
        store.close()


def test_fixed_cutoff_pages_preserve_decision_phases(tmp_path):
    """Late acknowledgements cannot enter an earlier 257-admission snapshot."""
    store = _StateStore(str(tmp_path / "cohort.db"))
    provenance = {
        "policy_snapshot_hash": "a" * 64,
        "admission_boundary": "validated_endpoint",
        "measurement_unit": "http_request",
        "metric_scope": "initial_task_route_decision",
        "selection_elapsed_ns": None,
        "durable_ack_elapsed_ns": None,
        "first_provider_elapsed_ns": None,
    }
    try:
        for request_index in range(257):
            request_id = f"request_{request_index:03d}"
            store.save("accepted_request", request_id,
                       {**provenance, "request_id": request_id, "status": "accepted"}, durable=True)
        for request_id in ("request_000", "request_255"):
            store.save("initial_decision", request_id,
                       {**provenance, "request_id": request_id, "status": "selected",
                        "selection_elapsed_ns": 123}, durable=True)
        store.save("decision_receipt", "request_000",
                   {**provenance, "request_id": "request_000", "status": "acknowledged",
                    "selection_elapsed_ns": 123, "durable_ack_elapsed_ns": 456,
                    "first_provider_elapsed_ns": 789}, durable=True)
        first_page = store.export_request_outcomes(page_size=200)
        store.save("decision_receipt", "request_255",
                   {**provenance, "request_id": "request_255", "status": "acknowledged",
                    "selection_elapsed_ns": 123, "durable_ack_elapsed_ns": 999}, durable=True)
        second_page = store.export_request_outcomes(
            page_size=200, after_sequence=first_page["next_after_sequence"],
            high_water_sequence=first_page["high_water_sequence"],
        )
        rows = first_page["observations"] + second_page["observations"]
        assert [len(first_page["observations"]), len(second_page["observations"])] == [200, 57]
        assert len({row["admission_sequence"] for row in rows}) == 257
        assert second_page["next_after_sequence"] is None
        assert first_page["measurement_complete"] is False
        assert second_page["reconciliation_required"] is True
        for row in rows:
            for field_name in ("policy_snapshot_hash", "admission_boundary", "measurement_unit", "metric_scope"):
                assert row[field_name] == provenance[field_name]
        assert rows[0]["selection_elapsed_ns"] == 123
        assert rows[0]["durable_ack_elapsed_ns"] == 456
        assert rows[0]["decision_latency_ms"] == 456 / 1_000_000
        assert rows[0]["first_provider_elapsed_ns"] == 789
        assert rows[255]["decision_status"] == "acknowledgement_unobserved"
        assert rows[255]["selection_elapsed_ns"] == 123
        assert rows[255]["durable_ack_elapsed_ns"] is None
        assert rows[255]["decision_latency_ms"] is None
        assert rows[256]["decision_status"] == "unfinished"
        assert rows[256]["selection_elapsed_ns"] is None
        assert rows[256]["durable_ack_elapsed_ns"] is None
        assert rows[256]["decision_latency_ms"] is None
    finally:
        store.close()
