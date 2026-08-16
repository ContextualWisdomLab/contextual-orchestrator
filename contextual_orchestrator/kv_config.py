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

import os
import threading
from typing import Any, Dict, Iterable, NamedTuple, Optional, Protocol, Tuple

PROVIDER_EGRESS_CATEGORY = "provider_egress"
ALLOWED_PROVIDER_HOSTS_KEY = "allowed_provider_hosts"
_ALLOWED_HOSTS_ENV = "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS"

PROCESS_BOOTSTRAP_CATEGORY = "process_bootstrap"
STATE_DATABASE_PATH_KEY = "state_database_path"
AGENTS_DATABASE_PATH_KEY = "agents_database_path"
CLEARFOLIO_VIEWER_URL_KEY = "clearfolio_viewer_url"
PROVIDER_CA_BUNDLE_KEY = "provider_ca_bundle"
_PROCESS_BOOTSTRAP_ENV = {
    STATE_DATABASE_PATH_KEY: "CONTEXTUAL_ORCHESTRATOR_STATE_DB",
    AGENTS_DATABASE_PATH_KEY: "CONTEXTUAL_ORCHESTRATOR_AGENTS_DB",
    CLEARFOLIO_VIEWER_URL_KEY: "CONTEXTUAL_ORCHESTRATOR_CLEARFOLIO_URL",
    PROVIDER_CA_BUNDLE_KEY: "CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE",
}

_runtime_store: ConfigStore | None = None
_runtime_lock = threading.Lock()


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


def get_runtime_config_store() -> ConfigStore:
    """Return the process-wide KV used at request time (created on first use)."""
    global _runtime_store
    if _runtime_store is None:
        with _runtime_lock:
            if _runtime_store is None:
                _runtime_store = InMemoryConfigStore()
    return _runtime_store


def set_runtime_config_store(store: ConfigStore | None) -> None:
    """Install (or, with ``None``, reset) the process-wide request-time KV."""
    global _runtime_store
    with _runtime_lock:
        _runtime_store = store


def reset_runtime_config_store() -> None:
    """Drop the process-wide KV so the next read starts empty (tests)."""
    set_runtime_config_store(None)


def get_runtime_config(category: str, key: str, default: Any = None) -> Any:
    """Read one request-time config value from the process KV. Never os.getenv."""
    return get_runtime_config_store().get(category, key, default)


def set_runtime_config(category: str, key: str, value: Any) -> None:
    """Write one request-time config value into the process KV."""
    get_runtime_config_store().set(category, key, value)


def _parse_host_allowlist(raw: Any) -> frozenset[str]:
    """Split a CSV or sequence of hosts into a lower-cased frozenset."""
    if raw is None:
        return frozenset()
    if isinstance(raw, (list, tuple, set, frozenset)):
        tokens = [str(item) for item in raw]
    else:
        tokens = str(raw).split(",")
    return frozenset(token.strip().lower() for token in tokens if str(token).strip())


def allowed_provider_hosts() -> frozenset[str]:
    """Return the request-time provider host allowlist from the KV only.

    An empty set means "no extra hostname filter" — public HTTPS hosts still
    pass the private/loopback/reserved address checks in ``ModelClient``.
    """
    raw = get_runtime_config(PROVIDER_EGRESS_CATEGORY, ALLOWED_PROVIDER_HOSTS_KEY, "")
    return _parse_host_allowlist(raw)


def seed_provider_egress_from_environ() -> None:
    """Bootstrap: copy the env allowlist into KV when that KV key is still empty.

    This is the only allowed ``os.environ`` read for the host allowlist.
    Request-time validation must call :func:`allowed_provider_hosts`.
    The empty-check and write share ``_runtime_lock`` so concurrent
    ``main()`` + ``serve()`` seeds cannot both observe an empty key.
    ``None``, ``""``, and whitespace-only values count as empty so a
    stored ``" "`` cannot freeze fail-open public HTTPS.
    """
    store = get_runtime_config_store()
    with _runtime_lock:
        existing = store.get(PROVIDER_EGRESS_CATEGORY, ALLOWED_PROVIDER_HOSTS_KEY, None)
        if existing is not None and str(existing).strip():
            return
        raw = os.environ.get(_ALLOWED_HOSTS_ENV, "")
        if raw.strip():
            store.set(PROVIDER_EGRESS_CATEGORY, ALLOWED_PROVIDER_HOSTS_KEY, raw)


class ProcessBootstrapSettings(NamedTuple):
    """Resolved sqlite / Clearfolio / provider-CA paths from CLI or the process KV."""

    state_database_path: str | None
    agents_database_path: str | None
    clearfolio_viewer_url: str | None
    provider_ca_bundle: str | None


def _optional_config_text(raw: Any) -> str | None:
    """Return a stripped string, or ``None`` when the value is empty or whitespace."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _first_process_bootstrap_text(explicit: str | None, key: str) -> str | None:
    """Prefer a non-empty explicit value; otherwise read the process KV."""
    chosen = _optional_config_text(explicit)
    if chosen is not None:
        return chosen
    return _optional_config_text(get_runtime_config(PROCESS_BOOTSTRAP_CATEGORY, key, None))


def resolve_process_bootstrap(
    *,
    state_database_path: str | None = None,
    agents_database_path: str | None = None,
    clearfolio_viewer_url: str | None = None,
    provider_ca_bundle: str | None = None,
) -> ProcessBootstrapSettings:
    """Return process sqlite/Clearfolio/CA settings. CLI wins; else the process KV.

    Never reads ``os.getenv``. Empty and whitespace-only values are omitted so a
    stored ``" "`` cannot freeze the in-memory default.
    """
    return ProcessBootstrapSettings(
        state_database_path=_first_process_bootstrap_text(
            state_database_path, STATE_DATABASE_PATH_KEY
        ),
        agents_database_path=_first_process_bootstrap_text(
            agents_database_path, AGENTS_DATABASE_PATH_KEY
        ),
        clearfolio_viewer_url=_first_process_bootstrap_text(
            clearfolio_viewer_url, CLEARFOLIO_VIEWER_URL_KEY
        ),
        provider_ca_bundle=_first_process_bootstrap_text(
            provider_ca_bundle, PROVIDER_CA_BUNDLE_KEY
        ),
    )


def seed_process_bootstrap_from_environ() -> None:
    """Bootstrap: copy sqlite/Clearfolio/CA env vars into KV when those keys are empty.

    This is the only allowed ``os.environ`` read for those process paths.
    Init-time constructors must call :func:`resolve_process_bootstrap`.
    The empty-check and write share ``_runtime_lock`` so concurrent
    ``main()`` + ``serve()`` seeds cannot both observe an empty key.
    ``None``, ``""``, and whitespace-only values count as empty.
    Gateway Bearer tokens stay on the #621 slice and are not copied here.
    """
    store = get_runtime_config_store()
    with _runtime_lock:
        for key, env_name in _PROCESS_BOOTSTRAP_ENV.items():
            existing = store.get(PROCESS_BOOTSTRAP_CATEGORY, key, None)
            if existing is not None and str(existing).strip():
                continue
            raw = os.environ.get(env_name, "")
            if raw.strip():
                store.set(PROCESS_BOOTSTRAP_CATEGORY, key, raw)
