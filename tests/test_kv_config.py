"""KV config seam: in-memory store surface, the pg_llm_batch adapter, and the
``get_config_store`` selector.

These run entirely on the dependency-free in-memory path plus small fakes for
the ``pg_llm_batch`` config/secret stores — no Postgres or ``pg_llm_batch``
install is needed. They pin the KV contract (``get``/``set``/``show_config`` +
the secret sub-surface) that ``credentials.py`` and the cost/routing hub read
config and provider secrets through, never ``os.getenv`` at runtime.
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


# --- InMemoryConfigStore ---------------------------------------------------


def test_in_memory_seed_is_loaded_via_set() -> None:
    """A ``seed`` mapping is materialised through ``set`` at construction."""
    store = InMemoryConfigStore(seed={"pricing": {"openai_input": 1.25}})
    assert store.get("pricing", "openai_input") == 1.25


def test_in_memory_get_returns_default_when_unset() -> None:
    """Reads of an absent category/key fall back to the supplied default."""
    store = InMemoryConfigStore()
    assert store.get("missing", "key") is None
    assert store.get("missing", "key", "fallback") == "fallback"


def test_in_memory_set_then_get_roundtrips() -> None:
    """A value written under a category/key is read back unchanged."""
    store = InMemoryConfigStore()
    store.set("routing", "batch_threshold", 42)
    assert store.get("routing", "batch_threshold") == 42


def test_in_memory_get_category_returns_a_copy() -> None:
    """``get_category`` returns a snapshot dict that does not alias internal state."""
    store = InMemoryConfigStore(seed={"routing": {"a": 1, "b": 2}})
    category = store.get_category("routing")
    assert category == {"a": 1, "b": 2}
    category["a"] = 999
    assert store.get("routing", "a") == 1  # mutation of the copy does not leak back
    assert store.get_category("absent") == {}


def test_in_memory_show_config_is_sorted() -> None:
    """``show_config`` yields every entry ordered by category then key."""
    store = InMemoryConfigStore()
    store.set("z_cat", "k2", "v2")
    store.set("z_cat", "k1", "v1")
    store.set("a_cat", "k", "v")
    assert list(store.show_config()) == [
        ("a_cat", "k", "v"),
        ("z_cat", "k1", "v1"),
        ("z_cat", "k2", "v2"),
    ]


def test_in_memory_secret_surface() -> None:
    """Secrets round-trip via ``set_secret``/``get_secret``/``require_secret`` and
    stay out of ``show_config``."""
    store = InMemoryConfigStore()
    store.set_secret("OPENAI_API_KEY", "sk-secret")
    assert store.get_secret("OPENAI_API_KEY") == "sk-secret"
    assert store.get_secret("absent") is None
    assert store.get_secret("absent", "dflt") == "dflt"
    assert store.require_secret("OPENAI_API_KEY") == "sk-secret"
    # A secret is never surfaced by the plain-config listing.
    assert all(name != "OPENAI_API_KEY" for _cat, name, _val in store.show_config())


def test_in_memory_require_secret_raises_when_absent() -> None:
    """``require_secret`` raises ``KeyError`` for an unconfigured secret."""
    store = InMemoryConfigStore()
    with pytest.raises(KeyError):
        store.require_secret("MISSING")


# --- PostgresConfigStoreAdapter (over fakes) -------------------------------


class _FakeConfig:
    """Minimal stand-in for ``pg_llm_batch.PostgresConfigStore``."""

    def __init__(self) -> None:
        self.tree: dict[tuple[str, str], object] = {}

    def get(self, category: str, key: str, default: object = None) -> object:
        return self.tree.get((category, key), default)

    def set(self, category: str, key: str, value: object) -> None:
        self.tree[(category, key)] = value


class _FakeSecret:
    """Minimal stand-in for ``pg_llm_batch.SecretStore``."""

    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    def require_secret(self, name: str) -> str:
        return self._secrets[name]  # raises KeyError when absent


def test_adapter_delegates_get_and_set() -> None:
    """The adapter forwards config reads/writes to the backing store."""
    backing = _FakeConfig()
    adapter = PostgresConfigStoreAdapter(backing)
    adapter.set("pricing", "input", 3.0)
    assert backing.tree[("pricing", "input")] == 3.0
    assert adapter.get("pricing", "input") == 3.0
    assert adapter.get("pricing", "missing", "dflt") == "dflt"


def test_adapter_get_secret_without_secret_store_returns_default() -> None:
    """With no secret store, ``get_secret`` returns the default rather than raising."""
    adapter = PostgresConfigStoreAdapter(_FakeConfig(), secret_store=None)
    assert adapter.get_secret("OPENAI_API_KEY") is None
    assert adapter.get_secret("OPENAI_API_KEY", "dflt") == "dflt"


def test_adapter_get_secret_delegates_and_swallows_errors() -> None:
    """``get_secret`` returns a configured secret, and degrades to the default
    when the backing store raises (e.g. secret absent)."""
    adapter = PostgresConfigStoreAdapter(
        _FakeConfig(), secret_store=_FakeSecret({"OPENAI_API_KEY": "sk-x"})
    )
    assert adapter.get_secret("OPENAI_API_KEY") == "sk-x"
    assert adapter.get_secret("ABSENT", "dflt") == "dflt"


def test_adapter_require_secret_without_store_raises() -> None:
    """``require_secret`` raises ``KeyError`` when no secret store is attached."""
    adapter = PostgresConfigStoreAdapter(_FakeConfig(), secret_store=None)
    with pytest.raises(KeyError):
        adapter.require_secret("OPENAI_API_KEY")


def test_adapter_require_secret_delegates() -> None:
    """``require_secret`` returns the backing store's secret when present."""
    adapter = PostgresConfigStoreAdapter(
        _FakeConfig(), secret_store=_FakeSecret({"OPENAI_API_KEY": "sk-y"})
    )
    assert adapter.require_secret("OPENAI_API_KEY") == "sk-y"


# --- get_config_store selector --------------------------------------------


def test_get_config_store_without_dsn_is_in_memory() -> None:
    """No DSN yields the dependency-free in-memory store, seeded when asked."""
    store = get_config_store()
    assert isinstance(store, InMemoryConfigStore)
    seeded = get_config_store(seed={"routing": {"batch_threshold": 7}})
    assert isinstance(seeded, InMemoryConfigStore)
    assert seeded.get("routing", "batch_threshold") == 7
