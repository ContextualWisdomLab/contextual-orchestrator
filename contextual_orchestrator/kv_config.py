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
drop-in interchangeable.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Protocol, Tuple


class ConfigStore(Protocol):
    """Minimal KV config contract shared by every backend."""

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
        self._tree: Dict[str, Dict[str, Any]] = {}
        self._secrets: Dict[str, str] = {}
        if seed:
            for category, entries in seed.items():
                for key, value in entries.items():
                    self.set(category, key, value)

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """Return the value stored under ``category``/``key`` or ``default``."""
        return self._tree.get(category, {}).get(key, default)

    def set(self, category: str, key: str, value: Any) -> None:
        """Store ``value`` under ``category``/``key``."""
        self._tree.setdefault(category, {})[key] = value

    def get_category(self, category: str) -> Dict[str, Any]:
        """Return a copy of every key/value pair under ``category``."""
        return dict(self._tree.get(category, {}))

    def show_config(self) -> Iterable[Tuple[str, str, Any]]:
        """Yield ``(category, key, value)`` for every configured entry."""
        for category, entries in sorted(self._tree.items()):
            for key, value in sorted(entries.items()):
                yield category, key, value

    def set_secret(self, secret_name: str, secret_value: str) -> None:
        """Store a secret (kept apart from plain config, never surfaced by show_config)."""
        self._secrets[secret_name] = secret_value

    def get_secret(self, secret_name: str, default: Any = None) -> Any:
        """Return a stored secret or ``default`` when absent."""
        return self._secrets.get(secret_name, default)

    def require_secret(self, secret_name: str) -> str:
        """Return a stored secret, raising when it is not configured."""
        if secret_name not in self._secrets:
            raise KeyError(f"secret {secret_name!r} is not configured")
        return self._secrets[secret_name]


class PostgresConfigStoreAdapter:
    """Adapter exposing ``pg_llm_batch`` KV + secret stores as a :class:`ConfigStore`.

    Instantiated only when a DSN is supplied and ``pg_llm_batch`` is importable;
    keeps the orchestrator dependency-light while reusing the batch engine's
    audited ``com_config`` / ``com_secrets`` tables when Postgres is available.
    """

    def __init__(self, config_store: Any, secret_store: Any = None) -> None:
        self._config = config_store
        self._secret = secret_store

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """Delegate reads to the underlying ``PostgresConfigStore``."""
        return self._config.get(category, key, default)

    def set(self, category: str, key: str, value: Any) -> None:
        """Delegate writes to the underlying ``PostgresConfigStore``."""
        self._config.set(category, key, value)

    def get_secret(self, secret_name: str, default: Any = None) -> Any:
        """Return a secret from the backing ``SecretStore`` when configured."""
        if self._secret is None:
            return default
        try:
            return self._secret.require_secret(secret_name)
        except Exception:
            return default

    def require_secret(self, secret_name: str) -> str:
        """Return a required secret from the backing ``SecretStore``."""
        if self._secret is None:
            raise KeyError(f"secret {secret_name!r} is not configured")
        return self._secret.require_secret(secret_name)


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
    in-memory store so the orchestrator never hard-depends on Postgres.
    """
    if not postgres_dsn:
        return InMemoryConfigStore(seed=seed)
    try:  # pragma: no cover - exercised only with pg_llm_batch + Postgres present
        from pg_llm_batch import PostgresConfigStore, SecretStore  # type: ignore

        config_store = PostgresConfigStore(postgres_dsn)
        secret_store = SecretStore(postgres_dsn, fernet_key=fernet_key)
        adapter = PostgresConfigStoreAdapter(config_store, secret_store)
        if seed:
            for category, entries in seed.items():
                for key, value in entries.items():
                    adapter.set(category, key, value)
        return adapter
    except Exception:  # pragma: no cover - fall back when deps/DB unavailable
        return InMemoryConfigStore(seed=seed)


# Process-wide runtime config (mirrors credentials.set_backend for non-secret KV).
_runtime_config_store: Optional[ConfigStore] = None


def get_runtime_config_store() -> ConfigStore:
    """Return the process runtime config store (never secrets).

    Defaults to an empty in-memory store. Tests inject via
    :func:`set_runtime_config_store`. Request-time code must read tunables from
    here (or an injected store), not ``os.getenv``.
    """
    global _runtime_config_store
    if _runtime_config_store is None:
        _runtime_config_store = InMemoryConfigStore()
    return _runtime_config_store


def set_runtime_config_store(store: Optional[ConfigStore]) -> None:
    """Install or clear the process runtime config store (tests / bootstrap)."""
    global _runtime_config_store
    _runtime_config_store = store


def get_config_value(category: str, key: str, default: Any = None) -> Any:
    """Read one runtime config value from the process KV store."""
    return get_runtime_config_store().get(category, key, default)


def set_config_value(category: str, key: str, value: Any) -> None:
    """Write one runtime config value into the process KV store."""
    get_runtime_config_store().set(category, key, value)


PROVIDER_ALLOWED_HOSTS_KEY = "allowed_hosts"
PROVIDER_CONFIG_CATEGORY = "provider"
# Bootstrap-only env name: may seed the KV once, never used as the runtime source.
ALLOWED_PROVIDER_HOSTS_ENV = "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS"


def allowed_provider_hosts() -> set[str]:
    """Return the operator host allowlist from the runtime KV config store.

    Empty set means no extra host filter (public-IP checks still apply). When the
    KV has no value yet, a one-shot bootstrap may seed from
    ``CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS`` into the store and then
    only the store is authoritative.
    """
    import os

    store = get_runtime_config_store()
    raw = store.get(PROVIDER_CONFIG_CATEGORY, PROVIDER_ALLOWED_HOSTS_KEY, None)
    if raw is None:
        # One-shot bootstrap: seed even when the env is empty so a later env
        # mutation cannot re-seed the store after first read (KV purity).
        env_val = os.environ.get(ALLOWED_PROVIDER_HOSTS_ENV, "")
        seeded = env_val.strip() if isinstance(env_val, str) else ""
        store.set(PROVIDER_CONFIG_CATEGORY, PROVIDER_ALLOWED_HOSTS_KEY, seeded)
        raw = seeded
    if isinstance(raw, (list, tuple, set)):
        parts = [str(item) for item in raw]
    else:
        parts = str(raw).split(",")
    return {part.strip().lower() for part in parts if part and str(part).strip()}
