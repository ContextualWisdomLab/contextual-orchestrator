"""KV config-store seam: in-memory store, Postgres adapter, and factory.

Runs entirely on the dependency-free in-memory backend plus lightweight fakes
standing in for the ``pg_llm_batch`` Postgres config/secret stores — no
Postgres or ``pg_llm_batch`` install required.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.kv_config import (  # noqa: E402
    InMemoryConfigStore,
    PostgresConfigStoreAdapter,
    get_config_store,
)


def test_in_memory_store_seeds_nested_entries() -> None:
    """A seed mapping is loaded into the nested category/key store."""
    store = InMemoryConfigStore(seed={"price_table": {"gpt_example": 1.0}})
    assert store.get("price_table", "gpt_example") == 1.0


def test_in_memory_get_returns_default_when_unset() -> None:
    """get() returns the supplied default for an unset key."""
    store = InMemoryConfigStore()
    assert store.get("routing_policy", "missing_key", "fallback_value") == "fallback_value"


def test_in_memory_get_category_returns_defensive_copy() -> None:
    """get_category returns a copy that cannot mutate the backing store."""
    store = InMemoryConfigStore(seed={"routing_policy": {"sync_threshold": 5}})
    category = store.get_category("routing_policy")
    assert category == {"sync_threshold": 5}
    category["sync_threshold"] = 99  # mutating the copy must not leak into the store
    assert store.get("routing_policy", "sync_threshold") == 5


def test_in_memory_get_category_missing_is_empty() -> None:
    """get_category returns an empty dict for an unknown category."""
    assert InMemoryConfigStore().get_category("absent_category") == {}


def test_in_memory_show_config_yields_sorted_entries() -> None:
    """show_config yields every (category, key, value) in sorted order."""
    store = InMemoryConfigStore()
    store.set("beta_group", "second_key", 2)
    store.set("alpha_group", "first_key", 1)
    assert list(store.show_config()) == [
        ("alpha_group", "first_key", 1),
        ("beta_group", "second_key", 2),
    ]


def test_in_memory_secret_roundtrip_and_not_shown_in_config() -> None:
    """Secrets round-trip through set/get and never appear in show_config."""
    store = InMemoryConfigStore()
    store.set_secret("openai_api_key", "sk-live")
    assert store.get_secret("openai_api_key") == "sk-live"
    assert list(store.show_config()) == []


def test_in_memory_get_secret_default_when_absent() -> None:
    """get_secret returns the supplied default for an unknown secret."""
    assert InMemoryConfigStore().get_secret("absent_secret", "default_value") == "default_value"


def test_in_memory_require_secret_returns_stored_value() -> None:
    """require_secret returns the stored value when the secret exists."""
    store = InMemoryConfigStore()
    store.set_secret("api_token", "value_one")
    assert store.require_secret("api_token") == "value_one"


def test_in_memory_require_secret_raises_when_missing() -> None:
    """require_secret raises KeyError for an unconfigured secret."""
    with pytest.raises(KeyError):
        InMemoryConfigStore().require_secret("absent_secret")


class _FakeConfigStore:
    """Minimal stand-in for ``pg_llm_batch.PostgresConfigStore``."""

    def __init__(self) -> None:
        """Start with an empty key/value map."""
        self._pairs: dict = {}

    def get(self, category: str, key: str, default=None):
        """Return the value under ``(category, key)`` or ``default``."""
        return self._pairs.get((category, key), default)

    def set(self, category: str, key: str, value) -> None:
        """Store ``value`` under ``(category, key)``."""
        self._pairs[(category, key)] = value


class _FakeSecretStore:
    """Minimal stand-in for ``pg_llm_batch.SecretStore``."""

    def __init__(self, known=None) -> None:
        """Seed the fake with a mapping of known secrets."""
        self._known = dict(known or {})

    def require_secret(self, secret_name: str) -> str:
        """Return a known secret or raise, mirroring the real store."""
        if secret_name not in self._known:
            raise KeyError(secret_name)
        return self._known[secret_name]


def test_postgres_adapter_delegates_get_and_set() -> None:
    """The adapter forwards get/set to the backing config store."""
    adapter = PostgresConfigStoreAdapter(_FakeConfigStore())
    adapter.set("price_table", "gpt_example", 2.5)
    assert adapter.get("price_table", "gpt_example") == 2.5
    assert adapter.get("price_table", "absent_key", "default_value") == "default_value"


def test_postgres_adapter_get_secret_without_store_returns_default() -> None:
    """With no secret store, get_secret returns the default."""
    adapter = PostgresConfigStoreAdapter(_FakeConfigStore(), secret_store=None)
    assert adapter.get_secret("openai_api_key", "fallback_value") == "fallback_value"


def test_postgres_adapter_get_secret_returns_backing_value() -> None:
    """get_secret returns the value from the backing secret store."""
    adapter = PostgresConfigStoreAdapter(_FakeConfigStore(), _FakeSecretStore({"api_token": "secret_v"}))
    assert adapter.get_secret("api_token") == "secret_v"


def test_postgres_adapter_get_secret_swallows_backend_error() -> None:
    """get_secret returns the default when the backing store raises."""
    adapter = PostgresConfigStoreAdapter(_FakeConfigStore(), _FakeSecretStore({}))
    assert adapter.get_secret("absent_secret", "default_on_error") == "default_on_error"


def test_postgres_adapter_require_secret_without_store_raises() -> None:
    """require_secret raises KeyError when no secret store is configured."""
    adapter = PostgresConfigStoreAdapter(_FakeConfigStore(), secret_store=None)
    with pytest.raises(KeyError):
        adapter.require_secret("api_token")


def test_postgres_adapter_require_secret_delegates() -> None:
    """require_secret delegates to the backing secret store."""
    adapter = PostgresConfigStoreAdapter(_FakeConfigStore(), _FakeSecretStore({"api_token": "value_one"}))
    assert adapter.require_secret("api_token") == "value_one"


def test_get_config_store_without_dsn_is_in_memory() -> None:
    """With no DSN the factory returns a seeded in-memory config store."""
    store = get_config_store(seed={"price_table": {"gpt_example": 1.0}})
    assert isinstance(store, InMemoryConfigStore)
    assert store.get("price_table", "gpt_example") == 1.0
