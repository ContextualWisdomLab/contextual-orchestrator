"""Behavioural coverage for the KV config, token-counting, and credential seams.

These exercise the standalone/adapter code paths that need no Postgres: the
in-memory config store surface, the ``pg_llm_batch`` adapter shims (driven by a
fake counter/store), the heuristic token estimator's edge cases, and the
credential backend bootstrap/selection rules. Each test asserts real behaviour,
not just execution.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import credentials  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    NotConfigured,
    PostgresCredentialBackend,
)
from contextual_orchestrator.kv_config import (  # noqa: E402
    InMemoryConfigStore,
    PostgresConfigStoreAdapter,
    get_config_store,
)
from contextual_orchestrator.token_counting import (  # noqa: E402
    HeuristicTokenCounter,
    PgTiktokenAdapter,
    build_token_counter,
)


# ---------------------------------------------------------------------------
# kv_config
# ---------------------------------------------------------------------------


def test_get_config_store_without_dsn_returns_in_memory_with_seed() -> None:
    store = get_config_store(seed={"routing": {"batch_enabled": False}})
    assert isinstance(store, InMemoryConfigStore)
    assert store.get("routing", "batch_enabled") is False
    assert store.get("routing", "missing_key", "fallback") == "fallback"


def test_in_memory_config_store_category_and_show_config_and_secrets() -> None:
    store = InMemoryConfigStore()
    store.set("routing", "batch_min_tokens", 500)
    store.set("routing", "batch_enabled", True)
    store.set("pricing", "currency_code", "USD")

    assert store.get_category("routing") == {"batch_min_tokens": 500, "batch_enabled": True}
    # get_category returns a copy; mutating it must not touch the store.
    store.get_category("routing")["batch_min_tokens"] = -1
    assert store.get("routing", "batch_min_tokens") == 500

    rows = list(store.show_config())
    assert ("pricing", "currency_code", "USD") in rows
    assert ("routing", "batch_enabled", True) in rows

    store.set_secret("provider_api_key", "sk-secret")
    assert store.get_secret("provider_api_key") == "sk-secret"
    assert store.get_secret("absent_secret", "default_value") == "default_value"
    assert store.require_secret("provider_api_key") == "sk-secret"
    with pytest.raises(KeyError):
        store.require_secret("absent_secret")
    # Secrets never leak through the plain-config listing.
    assert all(key != "provider_api_key" for _cat, key, _val in store.show_config())


def test_postgres_config_store_adapter_delegates_reads_writes_and_secrets() -> None:
    backing = InMemoryConfigStore()

    class _SecretStore:
        def __init__(self) -> None:
            self._store = {"kv_secret": "unlocked"}

        def require_secret(self, name: str) -> str:
            return self._store[name]

    adapter = PostgresConfigStoreAdapter(backing, _SecretStore())
    adapter.set("routing", "batch_enabled", True)
    assert adapter.get("routing", "batch_enabled") is True
    assert adapter.get("routing", "absent", "fallback") == "fallback"
    assert adapter.get_secret("kv_secret") == "unlocked"
    # Missing secret -> require raises through the backend KeyError; get returns default.
    assert adapter.get_secret("absent", "default_value") == "default_value"
    assert adapter.require_secret("kv_secret") == "unlocked"


def test_postgres_config_store_adapter_without_secret_store_is_default_only() -> None:
    adapter = PostgresConfigStoreAdapter(InMemoryConfigStore())
    assert adapter.get_secret("anything", "fallback") == "fallback"
    with pytest.raises(KeyError):
        adapter.require_secret("anything")


# ---------------------------------------------------------------------------
# token_counting
# ---------------------------------------------------------------------------


def test_heuristic_token_counter_empty_and_whitespace_are_zero() -> None:
    counter = HeuristicTokenCounter()
    assert counter.count_text("") == 0
    # Whitespace-only text has no word-ish units, so it counts as zero.
    assert counter.count_text("   \t\n ") == 0
    # Real words expand by the BPE factor and never fall below one.
    assert counter.count_text("one two three") == 4  # ceil(3 * 1.3)


def test_pg_tiktoken_adapter_delegates_text_and_messages() -> None:
    class _FakeCounter:
        def count_tokens(self, text: str, model: str) -> int:
            return len(text)

    adapter = PgTiktokenAdapter(_FakeCounter())
    assert adapter.count_text("abcd", "gpt-x") == 4
    # count_messages sums per-message text counts (no per-message framing here).
    assert adapter.count_messages([{"content": "ab"}, {"content": "cde"}, "skip"], "gpt-x") == 5


def test_build_token_counter_without_dsn_is_heuristic() -> None:
    assert isinstance(build_token_counter(), HeuristicTokenCounter)
    assert isinstance(build_token_counter(postgres_dsn=None), HeuristicTokenCounter)


# ---------------------------------------------------------------------------
# credentials
# ---------------------------------------------------------------------------


def test_postgres_credential_backend_requires_bootstrap_dsn_and_passphrase() -> None:
    with pytest.raises(NotConfigured):
        PostgresCredentialBackend("", "passphrase")
    with pytest.raises(NotConfigured):
        PostgresCredentialBackend("postgresql://db", "")
    backend = PostgresCredentialBackend("postgresql://db", "passphrase")
    assert backend._dsn == "postgresql://db"
    assert backend._passphrase == "passphrase"
    assert backend._ensured is False


def test_postgres_credential_backend_from_env_reads_bootstrap_transport(monkeypatch) -> None:
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_KV_DSN", "postgresql://boot")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE", "boot-pass")
    backend = PostgresCredentialBackend.from_env()
    assert backend._dsn == "postgresql://boot"
    assert backend._passphrase == "boot-pass"


def test_select_backend_postgres_selector_builds_postgres_backend(monkeypatch) -> None:
    credentials.set_backend(None)
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_KV_BACKEND", "postgres")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_KV_DSN", "postgresql://boot")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE", "boot-pass")
    try:
        backend = credentials.get_backend()
        assert isinstance(backend, PostgresCredentialBackend)
    finally:
        credentials.set_backend(None)


def test_select_backend_memory_selector_is_default(monkeypatch) -> None:
    credentials.set_backend(None)
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_KV_BACKEND", raising=False)
    try:
        assert isinstance(credentials.get_backend(), InMemoryCredentialBackend)
    finally:
        credentials.set_backend(None)


if __name__ == "__main__":  # pragma: no cover
    import types

    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and isinstance(_fn, types.FunctionType):
            # Tests using pytest fixtures (monkeypatch) are skipped in script mode.
            if _fn.__code__.co_argcount == 0:
                _fn()
                print(f"ok {_name}")
    print("ok")
