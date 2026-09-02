"""Key/value configuration + secret seam for the cost-review and routing hub.

Every tunable the cost/routing layer needs — price tables, routing thresholds,
batch-backend endpoints, credentials — is read from a KV store, **never** from
``os.getenv`` at runtime. Two backends are provided:

* :class:`InMemoryConfigStore` — the always-available, dependency-free default
  used for standalone runs, tests, and the mock/local path.
* A thin adapter over an installed ``pg_llm_batch.PostgresConfigStore`` /
  ``pg_llm_batch.SecretStore`` when a Postgres DSN is supplied via
  :func:`get_config_store`. The DSN itself is the only bootstrap transport;
  it is passed in explicitly by the caller, not resolved from the environment
  here.

The ``get(category, key, default)`` / ``set(category, key, value)`` shape is
deliberately identical to ``pg_llm_batch.PostgresConfigStore`` so the two are
drop-in interchangeable. Those generic parameter names are therefore retained
only at that external compatibility boundary; organization-owned internals use
bounded-context names.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Protocol, Tuple

# Sentinel distinguishing "no value stored" from any real stored value
# (including ``None``) when probing a category/key pair during migration.
_MISSING_CONFIG_VALUE = object()

# Renamed KV categories that may already hold persisted rows under their old
# name on a Postgres-backed deployment (``pg_llm_batch.PostgresConfigStore``
# keys each value at the literal ``f"{category}.{key}"`` string as a SQL
# PRIMARY KEY, so a bare category rename silently orphans any row already
# written under the old identity -- see ContextualWisdomLab/contextual-orchestrator#1017
# review discussion). Each entry names the finite, explicitly enumerated set
# of keys this codebase has ever written under the old category; the
# ``ConfigStore`` protocol has no category-enumeration method, so unknown
# keys cannot be discovered automatically. Bounded removal condition: delete
# an entry once every deployment has booted at least once against the
# renamed category (tracked as a docs/product-technical-gap-baseline.md G-17
# follow-up in ContextualWisdomLab/.github).
_LEGACY_CATEGORY_MIGRATIONS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "routing": (
        "routing_config",
        (
            "batch_enabled",
            "interactive_forces_sync",
            "batch_min_tokens",
            "embedding_max_tokens_per_request",
            "embedding_max_chars_per_part",
            "embedding_max_inputs_per_request",
            "batch_job_retention_seconds",
        ),
    ),
}


def _migrate_legacy_categories(config_store: "ConfigStore") -> None:
    """Backfill renamed KV categories so already-persisted values survive.

    Idempotent and additive only: a value already present under the new
    category name always wins and is never overwritten by this migration,
    so re-running it on every boot (including every reconnect/reload) is
    safe and produces one deterministic outcome regardless of call order.
    Only ``get``/``set`` are used, matching the minimal ``ConfigStore``
    protocol every backend (in-memory, the Postgres adapter, and test
    doubles) implements.
    """
    for legacy_category, (replacement_category, config_keys) in _LEGACY_CATEGORY_MIGRATIONS.items():
        for config_key in config_keys:
            if (
                config_store.get(
                    replacement_category,
                    config_key,
                    _MISSING_CONFIG_VALUE,
                )
                is not _MISSING_CONFIG_VALUE
            ):
                continue
            legacy_config_value = config_store.get(
                legacy_category,
                config_key,
                _MISSING_CONFIG_VALUE,
            )
            if legacy_config_value is not _MISSING_CONFIG_VALUE:
                config_store.set(
                    replacement_category,
                    config_key,
                    legacy_config_value,
                )


class ConfigStore(Protocol):
    """Minimal KV config contract shared by every backend.

    ``category``, ``key``, ``value`` and ``default`` intentionally mirror the
    released ``pg_llm_batch.PostgresConfigStore`` protocol and are treated as
    adapter-boundary vocabulary rather than organization-owned domain names.
    """

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """Return the configured value or ``default`` when unset."""
        ...

    def set(self, category: str, key: str, value: Any) -> None:
        """Persist a configuration value under ``category`` + ``key``."""
        ...


class InMemoryConfigStore:
    """Dependency-free KV config store backed by a nested dict.

    Suitable for standalone deployments and every test path. Mirrors the
    ``PostgresConfigStore`` surface (``get``/``set``/``show_config``) so callers
    do not care which backend they hold.
    """

    def __init__(self, seed: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._config_tree: Dict[str, Dict[str, Any]] = {}
        self._secret_values: Dict[str, str] = {}
        if seed:
            for config_category, category_entries in seed.items():
                for config_key, config_value in category_entries.items():
                    self.set(config_category, config_key, config_value)

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """Return the value stored under ``category``/``key`` or ``default``."""
        return self._config_tree.get(category, {}).get(key, default)

    def set(self, category: str, key: str, value: Any) -> None:
        """Store ``value`` under ``category``/``key``."""
        self._config_tree.setdefault(category, {})[key] = value

    def get_category(self, category: str) -> Dict[str, Any]:
        """Return a copy of every key/value pair under ``category``."""
        return dict(self._config_tree.get(category, {}))

    def show_config(self) -> Iterable[Tuple[str, str, Any]]:
        """Yield ``(category, key, value)`` for every configured entry."""
        for config_category, category_entries in sorted(self._config_tree.items()):
            for config_key, config_value in sorted(category_entries.items()):
                yield config_category, config_key, config_value

    def set_secret(self, secret_name: str, secret_value: str) -> None:
        """Store a secret (kept apart from plain config, never surfaced by show_config)."""
        self._secret_values[secret_name] = secret_value

    def get_secret(self, secret_name: str, default: Any = None) -> Any:
        """Return a stored secret or ``default`` when absent."""
        return self._secret_values.get(secret_name, default)

    def require_secret(self, secret_name: str) -> str:
        """Return a stored secret, raising when it is not configured."""
        if secret_name not in self._secret_values:
            raise KeyError(f"secret {secret_name!r} is not configured")
        return self._secret_values[secret_name]


class PostgresConfigStoreAdapter:
    """Adapter exposing ``pg_llm_batch`` KV + secret stores as a :class:`ConfigStore`.

    Instantiated only when a DSN is supplied and ``pg_llm_batch`` is importable;
    keeps the orchestrator dependency-light while reusing the batch engine's
    audited ``com_config`` / ``com_secrets`` tables when Postgres is available.
    """

    def __init__(self, config_store: Any, secret_store: Any = None) -> None:
        self._postgres_config_store = config_store
        self._postgres_secret_store = secret_store

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """Delegate reads to the underlying ``PostgresConfigStore``."""
        return self._postgres_config_store.get(category, key, default)

    def set(self, category: str, key: str, value: Any) -> None:
        """Delegate writes to the underlying ``PostgresConfigStore``."""
        self._postgres_config_store.set(category, key, value)

    def get_secret(self, secret_name: str, default: Any = None) -> Any:
        """Return a secret from the backing ``SecretStore`` when configured."""
        if self._postgres_secret_store is None:
            return default
        try:
            return self._postgres_secret_store.require_secret(secret_name)
        except Exception:
            return default

    def require_secret(self, secret_name: str) -> str:
        """Return a required secret from the backing ``SecretStore``."""
        if self._postgres_secret_store is None:
            raise KeyError(f"secret {secret_name!r} is not configured")
        return self._postgres_secret_store.require_secret(secret_name)


def get_config_store(
    postgres_dsn: Optional[str] = None,
    *,
    fernet_key: Optional[str] = None,
    seed: Optional[Dict[str, Dict[str, Any]]] = None,
) -> ConfigStore:
    """Return a KV config store.

    With no DSN, an :class:`InMemoryConfigStore` is returned (the standalone /
    test default). With a DSN, the ``pg_llm_batch`` Postgres-backed stores are
    used when ``pg_llm_batch`` is importable; otherwise the call degrades to the
    in-memory store so the orchestrator never hard-depends on Postgres. Once a
    Postgres-backed adapter has been constructed, however, compatibility
    migration failures propagate so a transient persistence outage cannot
    silently switch a live process to default/in-memory routing policy.
    """
    if not postgres_dsn:
        in_memory_config_store = InMemoryConfigStore(seed=seed)
        _migrate_legacy_categories(in_memory_config_store)
        return in_memory_config_store
    try:  # pragma: no cover - exercised only with pg_llm_batch + Postgres present
        from pg_llm_batch import PostgresConfigStore, SecretStore  # type: ignore

        postgres_config_store = PostgresConfigStore(postgres_dsn)
        postgres_secret_store = SecretStore(postgres_dsn, fernet_key=fernet_key)
        config_store_adapter = PostgresConfigStoreAdapter(
            postgres_config_store,
            postgres_secret_store,
        )
    except Exception:  # pragma: no cover - fall back when deps/DB cannot initialize
        in_memory_config_store = InMemoryConfigStore(seed=seed)
        _migrate_legacy_categories(in_memory_config_store)
        return in_memory_config_store

    if seed:
        for config_category, category_entries in seed.items():
            for config_key, config_value in category_entries.items():
                config_store_adapter.set(config_category, config_key, config_value)
    _migrate_legacy_categories(config_store_adapter)
    return config_store_adapter
