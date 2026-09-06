"""Administrator-owned model timeout policy must survive configuration changes."""

from pathlib import Path
import sqlite3

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator


def test_ordinary_patch_rejects_stale_timeout_snapshot(tmp_path: Path) -> None:
    """A priority edit cannot silently clear another writer's audited timeout."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    writer = TaskOrchestrator([model_agent], agents_db=database_path)
    stale = TaskOrchestrator([model_agent], agents_db=database_path)
    writer.patch_agent("default", model_agent.id, {"model_timeout_seconds": 7200})
    with pytest.raises(ValueError, match="reload"):
        stale.patch_agent("default", model_agent.id, {"priority": 7})
    assert stale._agent(model_agent.id).priority == model_agent.priority
    restored = TaskOrchestrator([model_agent], agents_db=database_path)
    assert restored._agent(model_agent.id).model_timeout_seconds == 7200
    assert restored._agent(model_agent.id).model_timeout_revision == 1


def test_model_timeout_policy_defaults_to_null() -> None:
    """An ordinary model has no administrator-imposed execution limit."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    assert model_agent.to_config()["model_timeout_seconds"] is None


def test_model_timeout_policy_accepts_large_finite_seconds(tmp_path: Path) -> None:
    """Valid seconds must not accidentally use SQLite's signed integer binding."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    orchestrator = TaskOrchestrator([model_agent], agents_db=database_path)
    orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": 2**63})
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT model_timeout_seconds FROM agent_pool WHERE agent_id = ?", (model_agent.id,)
        ).fetchone() == (float(2**63),)
    restored = TaskOrchestrator([model_agent], agents_db=database_path)
    assert restored._agent(model_agent.id).model_timeout_seconds == float(2**63)


def test_model_timeout_policy_migrates_existing_pool(tmp_path: Path) -> None:
    """An older normalized pool gains a null policy without losing its models."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    orchestrator = TaskOrchestrator([model_agent], agents_db=database_path)
    orchestrator.patch_agent("default", model_agent.id, {"priority": 7})
    with sqlite3.connect(database_path) as connection:
        connection.execute("ALTER TABLE agent_pool DROP COLUMN model_timeout_seconds")
    restored = TaskOrchestrator([model_agent], agents_db=database_path)
    assert restored._agent(model_agent.id).priority == 7
    assert restored._agent(model_agent.id).model_timeout_seconds is None


def test_model_timeout_policy_survives_restart_and_rediscovery(tmp_path: Path) -> None:
    """An explicit limit belongs to its model and remains until explicitly cleared."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    other_agent = ModelAgent("other_agent", "other-model")
    database_path = str(tmp_path / "agent-pool.db")
    orchestrator = TaskOrchestrator([model_agent, other_agent], agents_db=database_path)
    updated = orchestrator.patch_agent(
        "default", model_agent.id, {"model_timeout_seconds": 7200.5}
    )
    assert updated["model_timeout_seconds"] == 7200.5
    assert orchestrator._agent(other_agent.id).to_config()["model_timeout_seconds"] is None

    restored = TaskOrchestrator([model_agent, other_agent], agents_db=database_path)
    assert restored._agent(model_agent.id).to_config()["model_timeout_seconds"] == 7200.5
    restored.sync_discovered_agents([model_agent])
    updated = restored.patch_agent("default", model_agent.id, {"priority": 2})
    assert updated["model_timeout_seconds"] == 7200.5
    cleared = restored.patch_agent(
        "default", model_agent.id, {"model_timeout_seconds": None}
    )
    assert cleared["model_timeout_seconds"] is None
    restarted = TaskOrchestrator([model_agent, other_agent], agents_db=database_path)
    assert restarted._agent(model_agent.id).to_config()["model_timeout_seconds"] is None


@pytest.mark.parametrize("invalid_limit", [True, False, 0, -1, "90", float("nan"), float("inf")])
def test_model_timeout_policy_rejects_invalid_patch(invalid_limit: object) -> None:
    """Invalid administrator limits must be rejected without changing the model."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    orchestrator = TaskOrchestrator([model_agent])
    with pytest.raises((TypeError, ValueError)):
        orchestrator.patch_agent(
            "default", model_agent.id, {"model_timeout_seconds": invalid_limit}
        )
    assert orchestrator._agent(model_agent.id) == model_agent


@pytest.mark.parametrize("previous_limit", [None, 3600.0])
def test_model_timeout_policy_audit_failure_does_not_apply(
    tmp_path: Path, previous_limit: float | None
) -> None:
    """A rejected policy update must not leave a new durable or serving limit."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    orchestrator = TaskOrchestrator([model_agent], agents_db=database_path)
    if previous_limit is not None:
        orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": previous_limit})

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_timeout_history BEFORE INSERT ON model_timeout_history "
            "BEGIN SELECT RAISE(ABORT, 'audit storage unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="audit storage unavailable"):
        orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": 7200})
    restored = TaskOrchestrator([model_agent], agents_db=database_path)
    assert (
        orchestrator._agent(model_agent.id).model_timeout_seconds,
        restored._agent(model_agent.id).model_timeout_seconds,
    ) == (previous_limit, previous_limit)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM model_timeout_history").fetchone() == (
            int(previous_limit is not None),
        )


def test_model_timeout_policy_requires_durable_store() -> None:
    """Administrator policy cannot silently fall back to volatile memory."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    orchestrator = TaskOrchestrator([model_agent])
    with pytest.raises(ValueError, match="durable"):
        orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": 7200})
    assert orchestrator._agent(model_agent.id).model_timeout_seconds is None


def test_model_timeout_policy_records_atomic_history(tmp_path: Path) -> None:
    """Committed revisions retain their old and new limits in order."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    orchestrator = TaskOrchestrator([model_agent], agents_db=database_path)
    for limit in (7200, None):
        orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": limit})
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT previous_seconds, timeout_seconds FROM model_timeout_history "
            "WHERE agent_id = ? ORDER BY policy_revision", (model_agent.id,)
        ).fetchall() == [(None, 7200.0), (7200.0, None)]


def test_model_timeout_policy_rejects_stale_writer(tmp_path: Path) -> None:
    """A stale model view cannot overwrite a different committed timeout value."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    first = TaskOrchestrator([model_agent], agents_db=database_path)
    stale = TaskOrchestrator([model_agent], agents_db=database_path)
    first.patch_agent("default", model_agent.id, {"model_timeout_seconds": 7200})
    with pytest.raises(ValueError, match="reload"):
        stale.patch_agent("default", model_agent.id, {"model_timeout_seconds": 3600})
    restored = TaskOrchestrator([model_agent], agents_db=database_path)
    assert restored._agent(model_agent.id).model_timeout_seconds == 7200
    assert stale._agent(model_agent.id).model_timeout_seconds is None
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM model_timeout_history").fetchone() == (1,)


def test_model_timeout_policy_preserves_other_stored_attributes(tmp_path: Path) -> None:
    """A timeout-only write does not replay an old copy of unrelated attributes."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    first = TaskOrchestrator([model_agent], agents_db=database_path)
    stale = TaskOrchestrator([model_agent], agents_db=database_path)
    first.patch_agent("default", model_agent.id, {"priority": 9})
    stale.patch_agent("default", model_agent.id, {"model_timeout_seconds": 7200})
    restored = TaskOrchestrator([model_agent], agents_db=database_path)
    assert restored._agent(model_agent.id).priority == 9
    assert restored._agent(model_agent.id).model_timeout_seconds == 7200


def test_model_timeout_policy_rejects_aba_writer(tmp_path: Path) -> None:
    """Returning to null must not make an older policy snapshot current again."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    first = TaskOrchestrator([model_agent], agents_db=database_path)
    stale = TaskOrchestrator([model_agent], agents_db=database_path)
    for limit in (7200, None):
        first.patch_agent("default", model_agent.id, {"model_timeout_seconds": limit})
    with pytest.raises(ValueError, match="reload"):
        stale.patch_agent("default", model_agent.id, {"model_timeout_seconds": 3600})
    restored = TaskOrchestrator([model_agent], agents_db=database_path)
    assert restored._agent(model_agent.id).model_timeout_seconds is None
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM model_timeout_history").fetchone() == (2,)


def test_model_timeout_policy_loads_value_and_revision_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent commit cannot attach a new revision to an older value."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    writer = TaskOrchestrator([model_agent], agents_db=database_path)
    writer.patch_agent("default", model_agent.id, {"model_timeout_seconds": 3600})
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    reader = TaskOrchestrator([model_agent], agents_db=database_path)
    original_connect = reader._pool_store._connect
    updates = []

    def connect_with_interleaved_write(database: str) -> sqlite3.Connection:
        """Commit a second version after value selection but before history selection."""
        connection = original_connect(database)

        def on_query(statement: str) -> None:
            """Interleave one independently committed writer without sleeping."""
            if "SELECT agent_id, MAX(policy_revision)" in statement and not updates:
                updates.append(writer.patch_agent(
                    "default", model_agent.id, {"model_timeout_seconds": 7200}
                ))

        connection.set_trace_callback(on_query)
        return connection

    monkeypatch.setattr(reader._pool_store, "_connect", connect_with_interleaved_write)
    loaded = reader._pool_store.load_all()[0]
    assert len(updates) == 1
    assert (loaded.model_timeout_seconds, loaded.model_timeout_revision) == (3600, 1)


def test_model_timeout_policy_records_verified_principal(tmp_path: Path) -> None:
    """Policy history preserves the opaque principal supplied by the auth boundary."""
    from contextual_orchestrator.server import SecurityConfig

    security = SecurityConfig(admin_token="example_admin", inference_token="example_inference")
    headers = {"authorization": "Bearer example_admin"}
    security.authorize(headers, "admin", "127.0.0.1")
    principal_id = security.principal_id(headers)
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    orchestrator = TaskOrchestrator([model_agent], agents_db=database_path)
    orchestrator.patch_agent(
        "default", model_agent.id, {"model_timeout_seconds": 7200}, actor_id=principal_id
    )
    with sqlite3.connect(database_path) as connection:
        recorded = connection.execute("SELECT actor_id FROM model_timeout_history").fetchone()[0]
    assert recorded == principal_id
    assert "example_admin" not in recorded


@pytest.mark.parametrize("invalid_actor", [True, "example_admin", "A" * 64, "a" * 63])
def test_model_timeout_policy_rejects_raw_actor_values(tmp_path: Path, invalid_actor: object) -> None:
    """Reject raw or malformed actor values before writing policy or history."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    orchestrator = TaskOrchestrator([model_agent], agents_db=database_path)
    with pytest.raises(ValueError, match="opaque principal"):
        orchestrator.patch_agent(
            "default", model_agent.id, {"model_timeout_seconds": 7200}, actor_id=invalid_actor
        )
    assert orchestrator._agent(model_agent.id).model_timeout_seconds is None
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM model_timeout_history").fetchone() == (0,)


def test_model_timeout_policy_migrates_unknown_actor_history(tmp_path: Path) -> None:
    """Historical changes without actor evidence remain explicitly unattributed."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    orchestrator = TaskOrchestrator([model_agent], agents_db=database_path)
    orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": 7200})
    with sqlite3.connect(database_path) as connection:
        connection.execute("ALTER TABLE model_timeout_history DROP COLUMN actor_id")
    restored = TaskOrchestrator([model_agent], agents_db=database_path)
    assert restored._agent(model_agent.id).model_timeout_seconds == 7200
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT actor_id FROM model_timeout_history").fetchall() == [(None,)]


def test_model_timeout_policy_restore_creates_a_new_revision(tmp_path: Path) -> None:
    """Restore reuses a model's historical value without rewriting its history."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    orchestrator = TaskOrchestrator([model_agent], agents_db=database_path)
    first = orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": 7200})
    cleared = orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": None})
    restored = orchestrator.restore_model_timeout(
        "default", model_agent.id, first["model_timeout_revision"],
        expected_revision=cleared["model_timeout_revision"], actor_id="a" * 64,
    )
    assert restored["model_timeout_seconds"] == 7200
    assert restored["model_timeout_revision"] > cleared["model_timeout_revision"]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT previous_seconds, timeout_seconds, restored_from_revision, actor_id "
            "FROM model_timeout_history ORDER BY policy_revision DESC LIMIT 1"
        ).fetchone() == (None, 7200.0, first["model_timeout_revision"], "a" * 64)
        assert connection.execute("SELECT COUNT(*) FROM model_timeout_history").fetchone() == (3,)


def test_model_timeout_policy_restore_rejects_stale_revision(tmp_path: Path) -> None:
    """A restore based on an obsolete view cannot overwrite a newer policy."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    orchestrator = TaskOrchestrator([model_agent], agents_db=str(tmp_path / "agent-pool.db"))
    first = orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": 7200})
    orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": 3600})
    with pytest.raises(ValueError, match="reload"):
        orchestrator.restore_model_timeout(
            "default", model_agent.id, first["model_timeout_revision"],
            expected_revision=first["model_timeout_revision"], actor_id="a" * 64,
        )
    assert orchestrator._agent(model_agent.id).model_timeout_seconds == 3600


def test_model_timeout_policy_restore_rejects_foreign_history(tmp_path: Path) -> None:
    """A history identifier from another model does not authorize restoration."""
    first = ModelAgent("first_agent", "first-model")
    second = ModelAgent("second_agent", "second-model")
    orchestrator = TaskOrchestrator([first, second], agents_db=str(tmp_path / "agent-pool.db"))
    changed = orchestrator.patch_agent("default", first.id, {"model_timeout_seconds": 7200})
    with pytest.raises(KeyError, match="revision not found"):
        orchestrator.restore_model_timeout(
            "default", second.id, changed["model_timeout_revision"],
            expected_revision=0, actor_id="a" * 64,
        )
    assert orchestrator._agent(second.id).model_timeout_seconds is None


def test_model_timeout_policy_restore_audit_failure_rolls_back(tmp_path: Path) -> None:
    """A rejected restore must preserve its prior value and revision."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    database_path = str(tmp_path / "agent-pool.db")
    orchestrator = TaskOrchestrator([model_agent], agents_db=database_path)
    first = orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": 7200})
    latest = orchestrator.patch_agent("default", model_agent.id, {"model_timeout_seconds": None})
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_restore BEFORE INSERT ON model_timeout_history "
            "BEGIN SELECT RAISE(ABORT, 'restore audit unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="restore audit unavailable"):
        orchestrator.restore_model_timeout(
            "default", model_agent.id, first["model_timeout_revision"],
            expected_revision=latest["model_timeout_revision"], actor_id="a" * 64,
        )
    restored = TaskOrchestrator([model_agent], agents_db=database_path)
    assert restored._agent(model_agent.id).model_timeout_seconds is None
    assert restored._agent(model_agent.id).model_timeout_revision == latest["model_timeout_revision"]
    assert orchestrator._agent(model_agent.id).model_timeout_revision == latest["model_timeout_revision"]


@pytest.mark.parametrize("source_revision, expected_revision", [(True, 0), (0, 0), (2**63, 0), (1, True), (1, -1)])
def test_model_timeout_policy_restore_validates_revision_types(
    tmp_path: Path, source_revision: object, expected_revision: object
) -> None:
    """Reject malformed revision identifiers before history access or mutation."""
    model_agent = ModelAgent("timeout_agent", "example-model")
    orchestrator = TaskOrchestrator([model_agent], agents_db=str(tmp_path / "agent-pool.db"))
    with pytest.raises(ValueError):
        orchestrator.restore_model_timeout(
            "default", model_agent.id, source_revision,
            expected_revision=expected_revision, actor_id="a" * 64,
        )
    assert orchestrator._agent(model_agent.id).model_timeout_revision == 0
