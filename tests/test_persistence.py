"""Durable persistence: opt-in sqlite state store; in-memory default unchanged.

Process-local-only state is a production blocker — a restart loses every run,
audit trail, and analytics event. These assert state survives a restart when a
--state-db is set, and that the default stays purely in-memory.
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import _StateStore  # noqa: E402


def _orch(state_db: str | None = None) -> TaskOrchestrator:
    return TaskOrchestrator([ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))], state_db=state_db)


def test_runs_audit_analytics_survive_restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "state.db")

        first = _orch(db)
        record = first.run([{"role": "user", "content": "persist me"}])
        run_id = record["workflow_run_id"]
        evaluation = first.run_evaluation(["alpha", "beta"])
        analytics_count = len(first._analytics_events)
        audit_count = len(first._audit_events)
        first.close()

        # Simulate a restart: a brand-new orchestrator on the same db file.
        second = _orch(db)
        try:
            assert run_id in second._workflow_runs
            assert second.get_workflow_run(run_id)["answer"] == record["answer"]
            assert second.get_workflow_run(run_id)["prompt_text"] == "persist me"
            assert evaluation["evaluation_run_id"] in second._evaluation_runs
            assert run_id in second._run_order  # run order rebuilt from persisted runs
            assert len(second._analytics_events) == analytics_count
            assert len(second._audit_events) == audit_count
        finally:
            second.close()


def test_default_is_purely_in_memory() -> None:
    orchestrator = _orch()  # no state_db
    assert orchestrator._store is None
    orchestrator.run([{"role": "user", "content": "hi"}])
    # No db file, nothing to reload — a fresh default orchestrator starts empty.
    assert _orch()._workflow_runs == {}


def test_store_upserts_keyed_records_and_appends_streams() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = _StateStore(os.path.join(directory, "s.db"))
        store.save("workflow_run", "run_k1", {"workflow_run_id": "run_k1", "v": 1})
        store.save("workflow_run", "run_k1", {"workflow_run_id": "run_k1", "v": 2})  # upsert, not duplicate
        assert store.load("workflow_run") == [{"workflow_run_id": "run_k1", "v": 2}]

        store.save("audit", None, {"a": 1})
        store.save("audit", None, {"a": 2})
        assert store.load("audit") == [{"a": 1}, {"a": 2}]  # streams append in order
        assert store.load("audit", 1) == [{"a": 2}]  # limit keeps the newest
        store.close()


def test_store_treats_kind_key_and_limit_as_sql_parameters() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = _StateStore(os.path.join(directory, "s.db"))
        malicious_kind = "audit'; DROP TABLE records; --"
        malicious_key = "run_k1'; DROP TABLE records; --"
        store.save(malicious_kind, malicious_key, {"payload": "kind is data"})
        store.save("workflow_run", malicious_key, {"workflow_run_id": malicious_key, "v": 1})

        assert store.load(malicious_kind) == [{"payload": "kind is data"}]
        assert store.load("workflow_run", 1) == [{"workflow_run_id": malicious_key, "v": 1}]
        assert store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = ? AND name = ?",
            ("table", "records"),
        ).fetchone() == ("records",)

        try:
            store.load("workflow_run", "1; DROP TABLE records; --")  # type: ignore[arg-type]
        except sqlite3.IntegrityError:
            pass
        except sqlite3.OperationalError:
            pass
        assert store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = ? AND name = ?",
            ("table", "records"),
        ).fetchone() == ("records",)
        store.close()


def test_stream_reload_respects_deque_maxlen() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "state.db")
        first = _orch(db)
        maxlen = first._analytics_events.maxlen
        # Drive more analytics events than the deque can hold.
        for i in range(maxlen + 25):
            first.record_analytics_event("load_probe", {"i": i})
        assert len(first._analytics_events) == maxlen  # deque saturated
        first.close()

        second = _orch(db)
        try:
            assert len(second._analytics_events) == maxlen  # reload also capped
            assert second._analytics_events[-1]["event_detail"]["i"] == maxlen + 24  # newest kept
        finally:
            second.close()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
