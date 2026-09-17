"""Database fixture owners close connections after transaction completion."""

import sqlite3

import pytest

import test_agent_pool_db as pool_cases


@pytest.mark.parametrize("scenario_name", [
    "test_endpoint_equivalence_contract_is_normalized_and_survives_restart",
    "test_clearing_last_endpoint_member_reaps_its_orphan_contract",
    "test_add_patch_remove_survive_restart",
    "test_stream_usage_capability_patch_survives_restart",
    "test_add_agent_rejects_unpersistable_limit_without_mutation",
    "test_patch_agent_rejects_unpersistable_limit_without_mutation",
    "test_legacy_payload_group_is_migrated_without_data_loss",
    "test_agent_pool_storage_is_normalized_and_preserves_ordered_attributes",
    "test_legacy_agent_pool_payloads_migrate_transactionally",
    "test_malformed_legacy_agent_pool_rolls_back_without_losing_source",
])
def test_endpoint_fixture_closes_connections(monkeypatch, scenario_name) -> None:
    """The existing persistence scenario leaves no usable database handle."""
    original_connect = sqlite3.connect
    opened_connections = []

    def tracked_connect(*args, **kwargs):
        """Retain handles for explicit closure assertions, even on failure."""
        connection = original_connect(*args, **kwargs)
        opened_connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    try:
        getattr(pool_cases, scenario_name)()
        assert opened_connections
        for connection in opened_connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
                connection.execute("SELECT 1")
    finally:
        for connection in opened_connections:
            connection.close()
