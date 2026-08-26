"""DB-backed model-group (agent pool) management.

The pool was seed-file + in-memory only: runtime add/patch/remove evaporated on
restart. With agents_db, operator changes persist: stored rows overlay the seed at
startup, removal writes a disabled tombstone so even seed agents stay removed.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def _seed() -> list[ModelAgent]:
    return [ModelAgent("general_agent", "seed-model", tags=("reasoning", "writing"))]


NEW_AGENT = {
    "id": "coding_agent",
    "model": "gpt-5.5",
    "base_url": "https://api.openai.com/v1",
    "credential_key": "OPENAI_API_KEY",
    "tags": ["coding", "reasoning"],
    "priority": 2,
}


def _endpoint_contract() -> dict[str, object]:
    return {
        "contract_id": "shared_endpoint_contract",
        "model_revision": "revision_2026_08",
        "reasoning_effort_profile": "worker_medium",
        "capability_set": ("image", "text"),
        "structured_output_contract": "openai_compatible_v1",
        "accuracy_class": "provider_full_precision",
        "data_residency_policy": "kr_region_only",
        "retention_policy": "zero_retention",
        "context_limit": 128_000,
        "pricing_evidence_id": "catalog_snapshot_2026_08_26",
        "hedge_eligible": True,
        "cancellation_supported": False,
        "execution_policy": "immediate_race",
    }


def test_endpoint_equivalence_contract_is_normalized_and_survives_restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = os.path.join(directory, "endpoint-contract.db")
        first = TaskOrchestrator(_seed(), agents_db=database_path)
        first.patch_agent(
            "default", "general_agent", {"endpoint_equivalence": _endpoint_contract()}
        )
        second = TaskOrchestrator(_seed(), agents_db=database_path)
        assert second._agent("general_agent").endpoint_equivalence == _endpoint_contract()
        with sqlite3.connect(database_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM endpoint_equivalence_contract"
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT COUNT(*) FROM endpoint_equivalence_capability"
            ).fetchone() == (2,)
            assert connection.execute(
                "SELECT COUNT(*) FROM endpoint_equivalence_member"
            ).fetchone() == (1,)


def test_add_patch_remove_survive_restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "pool.db")

        first = TaskOrchestrator(_seed(), agents_db=db)
        first.add_agent("default", NEW_AGENT)
        first.patch_agent("default", "general_agent", {"priority": 9})
        first.set_model_group("example-logical-model", ["general_agent", "coding_agent"])
        assert {a.id for a in first.agents} == {"general_agent", "coding_agent"}

        second = TaskOrchestrator(_seed(), agents_db=db)  # restart with the same seed file
        by_id = {a.id: a for a in second.agents}
        assert set(by_id) == {"general_agent", "coding_agent"}  # added agent restored
        assert by_id["general_agent"].priority == 9  # patch restored over the seed
        assert by_id["coding_agent"].model == "gpt-5.5"
        assert {a.group_name for a in by_id.values()} == {"example_logical_model"}
        with sqlite3.connect(db) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_pool)")}
            assert "payload" not in columns  # normalized schema, no JSON shadow
            assert conn.execute("SELECT group_name FROM model_group").fetchall() == [
                ("example_logical_model",)
            ]
            assert set(conn.execute("SELECT agent_id FROM model_group_member").fetchall()) == {
                ("general_agent",),
                ("coding_agent",),
            }

        second.remove_agent("default", "coding_agent")
        third = TaskOrchestrator(_seed(), agents_db=db)
        assert {a.id for a in third.agents} == {"general_agent"}  # removal survived restart


def test_legacy_payload_group_is_migrated_without_data_loss() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "pool.db")
        legacy = ModelAgent("legacy_agent", "legacy-model", group_name="legacy-group").to_config()
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE agent_pool (agent_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            conn.execute("INSERT INTO agent_pool VALUES (?, ?)", ("legacy_agent", json.dumps(legacy)))

        restored = TaskOrchestrator([], agents_db=db)

        assert restored.candidates[0].group_name == "legacy_group"
        with sqlite3.connect(db) as conn:
            # The normalized pool has no payload column; membership lives in its
            # own relation and the legacy payload table is dropped after promotion.
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert "agent_pool_legacy_payloads" not in tables
            member = conn.execute(
                "SELECT group_name FROM model_group_member WHERE agent_id = 'legacy_agent'"
            ).fetchone()
            assert member is not None and member[0] == "legacy_group"


def test_seed_agent_removal_tombstones_across_restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "pool.db")
        seed = [
            ModelAgent("general_agent", "seed-model", tags=("reasoning",)),
            ModelAgent(
                "backup_worker",
                "seed-model",
                tags=("reasoning",),
                group_name="removed_model_group",
            ),
        ]
        first = TaskOrchestrator(list(seed), agents_db=db)
        first.remove_agent("default", "backup_worker")
        assert "backup_worker" not in first._group_router._members

        second = TaskOrchestrator(list(seed), agents_db=db)  # seed still lists backup_worker
        assert {a.id for a in second.agents} == {"general_agent"}  # tombstone wins over seed
        assert second.list_model_groups() == []


def test_agent_pool_storage_is_normalized_and_preserves_ordered_attributes() -> None:
    """Persist scalar fields and multi-valued fields in separate 3NF tables."""
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "pool.db")
        agent = ModelAgent(
            "ordered_agent",
            "model-x",
            tags=("second", "first"),
            provider_exclusions=("provider-b", "provider-a"),
            reasoning_effort_supported=False,
        )
        first = TaskOrchestrator([agent], agents_db=db)
        first._pool_store.save(agent)

        with sqlite3.connect(db) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_pool)")}
            assert "payload" not in columns
            assert "reasoning_effort_supported" in columns
            assert connection.execute("SELECT COUNT(*) FROM agent_pool").fetchone() == (1,)
            assert connection.execute("SELECT COUNT(*) FROM agent_pool_tags").fetchone() == (2,)
            assert connection.execute(
                "SELECT COUNT(*) FROM agent_pool_provider_exclusions"
            ).fetchone() == (2,)

        restored = TaskOrchestrator([], agents_db=db).agents
        assert restored == [agent]


def test_agent_pool_foreign_keys_reject_orphans_and_cascade_deletes() -> None:
    """Keep child rows attached to a parent on every runtime connection."""
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "pool.db")
        agent = ModelAgent("integrity_agent", "model-x")
        orchestrator = TaskOrchestrator([agent], agents_db=db)
        orchestrator._pool_store.save(agent)
        connection = orchestrator._pool_store._connect(db)
        try:
            assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO agent_pool_tags (agent_id, tag_position, tag_name) "
                    "VALUES (?, ?, ?)",
                    ("missing_agent", 0, "orphan"),
                )
            connection.execute(
                "INSERT INTO agent_pool_tags (agent_id, tag_position, tag_name) "
                "VALUES (?, ?, ?)",
                (agent.id, 0, "attached"),
            )
            connection.execute("DELETE FROM agent_pool WHERE agent_id = ?", (agent.id,))
            assert connection.execute(
                "SELECT COUNT(*) FROM agent_pool_tags WHERE agent_id = ?", (agent.id,)
            ).fetchone() == (0,)
        finally:
            connection.close()


def test_legacy_agent_pool_payloads_migrate_transactionally() -> None:
    """Upgrade legacy JSON rows while preserving their public agent contract."""
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "pool.db")
        legacy = ModelAgent(
            "legacy_agent",
            "legacy-model",
            tags=("reasoning", "coding"),
            provider_exclusions=("provider-x",),
            reasoning_effort_supported=True,
        )
        with sqlite3.connect(db) as connection:
            connection.execute(
                "CREATE TABLE agent_pool (agent_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO agent_pool (agent_id, payload) VALUES (?, ?)",
                (legacy.id, json.dumps(legacy.to_config())),
            )
            connection.commit()

        restored = TaskOrchestrator([], agents_db=db).agents
        assert restored == [legacy]
        with sqlite3.connect(db) as connection:
            assert connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("agent_pool_legacy_payloads",),
            ).fetchone() is None


def test_malformed_legacy_agent_pool_rolls_back_without_losing_source() -> None:
    """Reject malformed legacy data and leave the original table recoverable."""
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "pool.db")
        with sqlite3.connect(db) as connection:
            connection.execute(
                "CREATE TABLE agent_pool (agent_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO agent_pool (agent_id, payload) VALUES (?, ?)",
                ("broken_agent", "not-json"),
            )
            connection.commit()

        with pytest.raises(json.JSONDecodeError):
            TaskOrchestrator([ModelAgent("seed_agent", "unused")], agents_db=db)
        with sqlite3.connect(db) as connection:
            assert connection.execute(
                "SELECT payload FROM agent_pool WHERE agent_id = ?", ("broken_agent",)
            ).fetchone() == ("not-json",)
            legacy_columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_pool)")}
            assert legacy_columns == {"agent_id", "payload"}
            for table in ("agent_pool_tags", "agent_pool_provider_exclusions"):
                assert connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
                ).fetchone() is None


def test_add_agent_validations() -> None:
    orchestrator = TaskOrchestrator(_seed())
    for bad, why in [
        ({"model": "m"}, "missing id"),
        ({"id": "general_agent", "model": "m"}, "duplicate id"),
        ({"id": "http_agent", "model": "m", "base_url": "http://x.example/v1", "credential_key": "K"}, "http base_url"),
        ({"id": "nokey_agent", "model": "m", "base_url": "https://x.example/v1", "credential_key": ""}, "missing credential name"),
    ]:
        raised = False
        try:
            orchestrator.add_agent("default", bad)
        except ValueError:
            raised = True
        assert raised, why


def test_agent_pool_boundary_rejects_wrong_pool_without_mutation() -> None:
    """A worker ID cannot be patched or removed through another pool path."""
    orchestrator = TaskOrchestrator(_seed())
    for pool_id in ("other_pool", "default_", "", "DEFAULT"):
        try:
            orchestrator.patch_agent(pool_id, "general_agent", {"priority": 5})
        except KeyError:
            pass
        else:
            raise AssertionError(f"patch_agent accepted pool_id={pool_id!r}")
        try:
            orchestrator.remove_agent(pool_id, "general_agent")
        except KeyError:
            pass
        else:
            raise AssertionError(f"remove_agent accepted pool_id={pool_id!r}")
    assert orchestrator._agent("general_agent").priority == 0


def test_remove_last_enabled_agent_refused() -> None:
    orchestrator = TaskOrchestrator(_seed())
    raised = False
    try:
        orchestrator.remove_agent("default", "general_agent")
    except ValueError as exc:
        raised = True
        assert "last enabled" in str(exc)
    assert raised


def test_default_stays_in_memory() -> None:
    orchestrator = TaskOrchestrator(_seed())
    assert orchestrator._pool_store is None
    orchestrator.add_agent("default", {"id": "mock_worker", "model": "m2"})
    assert {a.id for a in TaskOrchestrator(_seed()).agents} == {"general_agent"}  # nothing persisted


def _call(url: str, method: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"content-type": "application/json", "authorization": f"Bearer {token}", "connection": "close"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_create_and_delete_worker_agents() -> None:
    token = "pool_token"
    orchestrator = TaskOrchestrator(_seed())
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api/v1/agent_pools/default/worker_agents"
    try:
        status, created = _call(base, "POST", token, NEW_AGENT)
        assert status == 201 and created["id"] == "coding_agent" and created["status"] == "active"

        status, dup = _call(base, "POST", token, NEW_AGENT)
        assert status == 400  # duplicate rejected

        status, wrong_pool = _call(
            f"http://127.0.0.1:{server.server_address[1]}"
            "/api/v1/agent_pools/other_pool/worker_agents/general_agent",
            "GET",
            token,
        )
        assert status == 404 and wrong_pool["error"]["code"] == "agent_not_found"

        status, wrong_pool_create = _call(
            f"http://127.0.0.1:{server.server_address[1]}"
            "/api/v1/agent_pools/other_pool/worker_agents",
            "POST",
            token,
            {**NEW_AGENT, "id": "other_agent"},
        )
        assert status == 404 and wrong_pool_create["error"]["code"] == "agent_not_found"

        status, unknown = _call(base, "POST", token, {**NEW_AGENT, "id": "extra_agent", "surprise": 1})
        assert status == 400 and unknown["error"]["code"] == "unknown_fields"

        status, removed = _call(f"{base}/coding_agent", "DELETE", token)
        assert status == 200 and removed["removed"] == "coding_agent"

        status, _ = _call(f"{base}/ghost_agent", "DELETE", token)
        assert status == 404
    finally:
        server.shutdown()
    assert {a.id for a in orchestrator.agents} == {"general_agent"}


def test_http_model_group_crud_uses_arbitrary_member_names() -> None:
    token = "pool_token"
    orchestrator = TaskOrchestrator(_seed())
    orchestrator.add_agent("default", NEW_AGENT)
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api/v1/model_groups"
    try:
        status, created = _call(base, "POST", token, {"group_name": "vendor-neutral-example", "member_agent_ids": ["general_agent", "coding_agent"]})
        assert status == 201 and created["group_name"] == "vendor_neutral_example"
        assert set(created["member_agent_ids"]) == {"general_agent", "coding_agent"}
        assert created["capability_coverage"] == {}

        status, duplicate = _call(base, "POST", token, {"group_name": "vendor-neutral-example", "member_agent_ids": ["coding_agent"]})
        assert status == 409 and duplicate["error"]["code"] == "model_group_exists"

        status, missing = _call(base, "POST", token, {"group_name": "missing-member", "member_agent_ids": ["ghost_agent"]})
        assert status == 404 and missing["error"]["code"] == "agent_not_found"

        status, missing = _call(f"{base}/missing-group", "PATCH", token, {"member_agent_ids": ["coding_agent"]})
        assert status == 404 and missing["error"]["code"] == "model_group_not_found"

        status, missing = _call(f"{base}/missing-group", "DELETE", token)
        assert status == 404 and missing["error"]["code"] == "model_group_not_found"

        status, listed = _call(base, "GET", token)
        assert status == 200 and listed["total_count"] == 1

        status, _ = _call(f"{base}/vendor-neutral-example", "PATCH", token, {"member_agent_ids": ["general_agent"]})
        assert status == 200
        status, completion = _call(
            base.replace("/api/v1/model_groups", "/v1/chat/completions"),
            "POST",
            token,
            {
                "model": "vendor-neutral-example",
                "messages": [{"role": "user", "content": "route the logical model"}],
            },
        )
        assert status == 200 and completion["model"] == "vendor-neutral-example"

        status, invalid = _call(
            base.replace("/api/v1/model_groups", "/v1/chat/completions"),
            "POST",
            token,
            {"model": "not.a.valid.group", "messages": [{"role": "user", "content": "reject"}]},
        )
        assert status == 400 and invalid["error"]["code"] == "invalid_model"

        status, updated = _call(f"{base}/vendor-neutral-example", "PATCH", token, {"member_agent_ids": ["coding_agent"]})
        assert status == 200 and updated["member_agent_ids"] == ["coding_agent"]

        status, deleted = _call(f"{base}/vendor-neutral-example", "DELETE", token)
        assert status == 200 and deleted["deleted"] is True
        assert orchestrator.list_model_groups() == []
    finally:
        server.shutdown()


def test_http_worker_agent_read_rejects_wrong_pool_id() -> None:
    """Every worker-agent verb must reject a different pool consistently."""
    token = "pool_token"
    orchestrator = TaskOrchestrator(_seed())
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        path = f"{base}/api/v1/agent_pools/wrong_pool/worker_agents/general_agent"
        for method, payload in (("GET", None), ("PATCH", {"status": "disabled"}), ("DELETE", None)):
            status, body = _call(path, method, token, payload)
            assert status == 404
            assert body["error"]["code"] == "agent_not_found"
    finally:
        server.shutdown()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
