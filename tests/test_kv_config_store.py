"""Behavioral coverage for configuration and secret storage boundaries."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from contextual_orchestrator.kv_config import (
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
