"""Behavioral coverage for configuration and secret storage boundaries."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from contextual_orchestrator.kv_config import (
    _LEGACY_CATEGORY_MIGRATIONS,
    InMemoryConfigStore,
    PostgresConfigStoreAdapter,
    get_config_store,
)


class _ConfigBackend:
    """Small pg_llm_batch-compatible config double with visible writes."""

    def __init__(self, postgres_dsn: str) -> None:
        self.postgres_dsn = postgres_dsn
        self.values: dict[tuple[str, str], Any] = {}

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """Return one stored value or the caller default."""
        return self.values.get((category, key), default)

    def set(self, category: str, key: str, value: Any) -> None:
        """Record one delegated write."""
        self.values[(category, key)] = value


class _SecretBackend:
    """Small pg_llm_batch-compatible secret double."""

    def __init__(self, postgres_dsn: str, *, fernet_key: str | None = None) -> None:
        self.postgres_dsn = postgres_dsn
        self.fernet_key = fernet_key
        self.values = {"OPENAI_API_KEY": "runtime-secret"}

    def require_secret(self, secret_name: str) -> str:
        """Return one configured secret or raise the backend lookup error."""
        return self.values[secret_name]


def test_in_memory_config_and_secrets_keep_their_boundaries() -> None:
    """Round-trip configuration while keeping secrets out of enumeration."""
    assert InMemoryConfigStore().get("routing_policy", "missing_key", "fallback") == "fallback"
    store = InMemoryConfigStore(
        {"routing_policy": {"quality_floor": 0.8}, "agent_pool": {"enabled": True}}
    )
    store.set("routing_policy", "quality_floor", 0.9)
    store.set_secret("OPENAI_API_KEY", "runtime-secret")

    assert store.get("routing_policy", "quality_floor") == 0.9
    assert store.get("routing_policy", "missing_key", "fallback") == "fallback"
    assert store.get_category("missing_category") == {}
    category = store.get_category("routing_policy")
    category["quality_floor"] = 0
    assert store.get("routing_policy", "quality_floor") == 0.9
    assert list(store.show_config()) == [
        ("agent_pool", "enabled", True),
        ("routing_policy", "quality_floor", 0.9),
    ]
    assert "runtime-secret" not in repr(list(store.show_config()))
    assert store.get_secret("OPENAI_API_KEY") == "runtime-secret"
    assert store.get_secret("MISSING_API_KEY", "fallback") == "fallback"
    assert store.require_secret("OPENAI_API_KEY") == "runtime-secret"
    with pytest.raises(KeyError, match="MISSING_API_KEY"):
        store.require_secret("MISSING_API_KEY")


def test_postgres_adapter_delegates_config_and_fails_closed_without_secrets() -> None:
    """Keep adapter configuration usable while absent secret storage stays closed."""
    config = _ConfigBackend("postgresql://example/config")
    adapter = PostgresConfigStoreAdapter(config)
    adapter.set("routing_policy", "quality_floor", 0.9)

    assert adapter.get("routing_policy", "quality_floor") == 0.9
    assert adapter.get("routing_policy", "missing_key", "fallback") == "fallback"
    assert adapter.get_secret("OPENAI_API_KEY", "fallback") == "fallback"
    with pytest.raises(KeyError, match="OPENAI_API_KEY"):
        adapter.require_secret("OPENAI_API_KEY")


def test_postgres_adapter_returns_secret_and_hides_lookup_failure() -> None:
    """Return authorized secrets but expose only the supplied default on lookup failure."""
    secrets = _SecretBackend("postgresql://example/config")
    adapter = PostgresConfigStoreAdapter(_ConfigBackend("postgresql://example/config"), secrets)

    assert adapter.get_secret("OPENAI_API_KEY") == "runtime-secret"
    assert adapter.require_secret("OPENAI_API_KEY") == "runtime-secret"
    assert adapter.get_secret("MISSING_API_KEY", "fallback") == "fallback"


def test_config_store_factory_uses_in_memory_backend_without_a_dsn() -> None:
    """Use the dependency-free backend when no database boundary is requested."""
    store = get_config_store(seed={"routing_policy": {"quality_floor": 0.8}})

    assert isinstance(store, InMemoryConfigStore)
    assert store.get("routing_policy", "quality_floor") == 0.8


def test_config_store_factory_builds_and_seeds_the_postgres_adapter(monkeypatch) -> None:
    """Pass the explicit DSN/key to pg_llm_batch and apply initial configuration."""
    module = types.ModuleType("pg_llm_batch")
    module.PostgresConfigStore = _ConfigBackend
    module.SecretStore = _SecretBackend
    monkeypatch.setitem(sys.modules, "pg_llm_batch", module)

    store = get_config_store(
        "postgresql://example/config",
        fernet_key="test-fernet-key",
        seed={"routing_policy": {"quality_floor": 0.8}},
    )

    assert isinstance(store, PostgresConfigStoreAdapter)
    assert store.get("routing_policy", "quality_floor") == 0.8
    assert store.get_secret("OPENAI_API_KEY") == "runtime-secret"
    assert store._config.postgres_dsn == "postgresql://example/config"
    assert store._secret.fernet_key == "test-fernet-key"


def test_config_store_factory_falls_back_when_postgres_is_unavailable(monkeypatch) -> None:
    """Retain caller seed values when the optional database backend cannot start."""
    class _UnavailableConfigBackend:
        def __init__(self, _postgres_dsn: str) -> None:
            raise ConnectionError("database unavailable")

    module = types.ModuleType("pg_llm_batch")
    module.PostgresConfigStore = _UnavailableConfigBackend
    module.SecretStore = _SecretBackend
    monkeypatch.setitem(sys.modules, "pg_llm_batch", module)

    store = get_config_store(
        "postgresql://example/config",
        seed={"routing_policy": {"quality_floor": 0.8}},
    )

    assert isinstance(store, InMemoryConfigStore)
    assert store.get("routing_policy", "quality_floor") == 0.8


def _postgres_backed_store(monkeypatch, backend: "_ConfigBackend"):
    """Return a ``get_config_store`` result backed by the given live-DSN double.

    ``backend`` stands in for the persisted ``pg_llm_batch.PostgresConfigStore``
    surface (``get``/``set`` over ``com_config``, keyed by ``category.key``
    exactly as the real Postgres table's primary key is built), so a value
    written into it before this call simulates a row a previous, unmigrated
    deployment already persisted to production Postgres.
    """
    module = types.ModuleType("pg_llm_batch")
    module.PostgresConfigStore = lambda dsn: backend
    module.SecretStore = _SecretBackend
    monkeypatch.setitem(sys.modules, "pg_llm_batch", module)
    return get_config_store("postgresql://example/config")


def test_renamed_category_backfills_every_key_already_persisted_under_the_old_name(
    monkeypatch,
) -> None:
    """A pre-existing Postgres row under a renamed category is not orphaned.

    RED without the ContextualWisdomLab/contextual-orchestrator#1017 review
    fix: renaming ``_ROUTING_CATEGORY``/``_EMBEDDING_CONFIG_CATEGORY`` from
    ``"routing"`` to ``"routing_config"`` at the call sites alone leaves any
    row a prior deployment already wrote under ``routing.<key>`` invisible to
    readers that now ask for ``routing_config.<key>`` -- ``PostgresConfigStore``
    keys ``com_config`` by the literal ``f"{category}.{key}"`` string, so the
    lookup is an exact miss and every caller silently falls back to its
    hardcoded Python default instead of the operator's persisted value.
    """
    legacy_category, (new_category, keys) = next(iter(_LEGACY_CATEGORY_MIGRATIONS.items()))
    backend = _ConfigBackend("postgresql://example/config")
    for index, key in enumerate(keys):
        backend.set(legacy_category, key, index)

    store = _postgres_backed_store(monkeypatch, backend)

    for index, key in enumerate(keys):
        assert store.get(new_category, key) == index


def test_renamed_category_migration_never_overwrites_an_explicit_new_value(
    monkeypatch,
) -> None:
    """An operator's explicit new-category value always wins over legacy backfill."""
    legacy_category, (new_category, keys) = next(iter(_LEGACY_CATEGORY_MIGRATIONS.items()))
    key = keys[0]
    backend = _ConfigBackend("postgresql://example/config")
    backend.set(legacy_category, key, "stale_legacy_value")
    backend.set(new_category, key, "explicit_new_value")

    store = _postgres_backed_store(monkeypatch, backend)

    assert store.get(new_category, key) == "explicit_new_value"


def test_renamed_category_migration_is_idempotent_across_reconnects(monkeypatch) -> None:
    """Re-running the migration on every reconnect/restart is stable, not clobbering.

    Simulates two process restarts against the same persisted backend: the
    first restart backfills the legacy value, an operator then explicitly
    reconfigures the new key, and a second restart must retain that explicit
    reconfiguration rather than re-copying the now-stale legacy row forward.
    """
    legacy_category, (new_category, keys) = next(iter(_LEGACY_CATEGORY_MIGRATIONS.items()))
    key = keys[0]
    backend = _ConfigBackend("postgresql://example/config")
    backend.set(legacy_category, key, "stale_legacy_value")

    first_boot = _postgres_backed_store(monkeypatch, backend)
    assert first_boot.get(new_category, key) == "stale_legacy_value"

    backend.set(new_category, key, "operator_reconfigured_value")

    second_boot = _postgres_backed_store(monkeypatch, backend)
    assert second_boot.get(new_category, key) == "operator_reconfigured_value"
    assert backend.get(legacy_category, key) == "stale_legacy_value"


def test_renamed_category_migration_also_backfills_the_in_memory_seed_path() -> None:
    """The same migration applies without a DSN, for seeded standalone/test runs."""
    legacy_category, (new_category, keys) = next(iter(_LEGACY_CATEGORY_MIGRATIONS.items()))
    key = keys[0]

    store = get_config_store(seed={legacy_category: {key: "seeded_legacy_value"}})

    assert isinstance(store, InMemoryConfigStore)
    assert store.get(new_category, key) == "seeded_legacy_value"
