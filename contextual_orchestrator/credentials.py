"""KV-backed credential resolution seam for runtime provider secrets.

ORG PRINCIPLE — "No os.getenv, values from KV"
------------------------------------------------
Runtime provider secrets (model provider API keys) are NEVER read from
``os.getenv``/raw environment at request time. They are resolved from a
pluggable credential registry via :func:`get_credential`.

Environment variables are permitted in exactly ONE place: as *bootstrap
transport* to connect to the KV itself — the Postgres DSN and the pgcrypto
passphrase used to open the encrypted registry, and the backend selector.
That is the single allowed env use in this module. The environment is never
the runtime *source* of a provider API key.

Backends are pluggable behind :class:`CredentialBackend`:

* :class:`InMemoryCredentialBackend` — default; dev/test, needs no Postgres.
* :class:`PostgresCredentialBackend` — pgcrypto-encrypted Postgres registry,
  consistent with the org reference pattern (xtrmLLMBatchPython's
  ``get_credential(name)`` over a pgp_sym_encrypt/decrypt column).

Backend selection is a bootstrap setting read from
``CONTEXTUAL_ORCHESTRATOR_KV_BACKEND`` (``memory`` default, or ``postgres``).
"""

from __future__ import annotations

import os
import threading
from typing import Protocol


class NotConfigured(RuntimeError):
    """Raised when a required credential cannot be resolved from the KV.

    This is deliberately distinct from a silent ``None``/env fallback: a
    non-mock agent whose credential is missing must fail loudly, never quietly
    read the environment.
    """


class CredentialBackend(Protocol):
    """Pluggable credential registry interface (a tiny KV of named secrets)."""

    def get(self, name: str) -> str | None:
        """Return the secret for ``name`` or ``None`` when it is not registered."""
        ...

    def set(self, name: str, value: str) -> None:
        """Register (or replace) the secret stored under ``name``."""
        ...


class InMemoryCredentialBackend:
    """Process-local credential registry for dev and tests (no Postgres needed)."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, name: str) -> str | None:
        """Return the in-memory secret for ``name`` or ``None``."""
        with self._lock:
            return self._store.get(name)

    def set(self, name: str, value: str) -> None:
        """Store ``value`` under ``name`` in the in-memory registry."""
        with self._lock:
            self._store[name] = value


# --- Postgres pgcrypto-encrypted credential registry ------------------------
#
# DB object naming follows the repo convention: NEW objects are 2+ word
# snake_case. The registry table is:
#
#   provider_credentials(
#       credential_name  text primary key,
#       encrypted_value  bytea not null,
#       updated_at       timestamptz not null default now()
#   )
#
# Secrets are encrypted at rest with pgcrypto's pgp_sym_encrypt and decrypted
# with pgp_sym_decrypt using a passphrase supplied at bootstrap.

PROVIDER_CREDENTIALS_TABLE = "provider_credentials"

CREATE_PROVIDER_CREDENTIALS_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS provider_credentials (
    credential_name text PRIMARY KEY,
    encrypted_value bytea NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""


class PostgresCredentialBackend:
    """pgcrypto-encrypted Postgres credential registry (org reference pattern).

    The Postgres DSN and the encryption passphrase are bootstrap transport into
    the KV and are the only permitted environment reads. They connect to and
    unlock the registry; they are never provider API keys themselves.
    """

    def __init__(self, dsn: str, passphrase: str) -> None:
        if not dsn:
            raise NotConfigured("Postgres credential backend requires a bootstrap DSN")
        if not passphrase:
            raise NotConfigured("Postgres credential backend requires a bootstrap passphrase")
        self._dsn = dsn
        self._passphrase = passphrase
        self._ensured = False

    @classmethod
    def from_env(cls) -> "PostgresCredentialBackend":
        """Build the backend from bootstrap transport env vars (the only allowed env use).

        ``CONTEXTUAL_ORCHESTRATOR_KV_DSN`` and
        ``CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`` open the encrypted KV; they are
        not runtime provider secrets.
        """
        return cls(
            dsn=os.environ.get("CONTEXTUAL_ORCHESTRATOR_KV_DSN", ""),
            passphrase=os.environ.get("CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE", ""),
        )

    def _connect(self):  # pragma: no cover - requires a live Postgres
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise NotConfigured(
                "PostgresCredentialBackend needs the 'db' extra (psycopg); "
                "install contextual-orchestrator[db]"
            ) from exc
        return psycopg.connect(self._dsn)

    def _ensure_schema(self, conn) -> None:  # pragma: no cover - requires a live Postgres
        if self._ensured:
            return
        with conn.cursor() as cur:
            cur.execute(CREATE_PROVIDER_CREDENTIALS_SQL)
        conn.commit()
        self._ensured = True

    def get(self, name: str) -> str | None:  # pragma: no cover - requires a live Postgres
        """Decrypt and return the secret for ``name`` via pgcrypto, or ``None``."""
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pgp_sym_decrypt(encrypted_value, %s) "
                    "FROM provider_credentials WHERE credential_name = %s",
                    (self._passphrase, name),
                )
                row = cur.fetchone()
        if row is None:
            return None
        value = row[0]
        return value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else value

    def set(self, name: str, value: str) -> None:  # pragma: no cover - requires a live Postgres
        """Encrypt ``value`` with pgcrypto and upsert it under ``name``."""
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO provider_credentials (credential_name, encrypted_value, updated_at) "
                    "VALUES (%s, pgp_sym_encrypt(%s, %s), now()) "
                    "ON CONFLICT (credential_name) DO UPDATE SET "
                    "encrypted_value = EXCLUDED.encrypted_value, updated_at = now()",
                    (name, value, self._passphrase),
                )
            conn.commit()


_backend: CredentialBackend | None = None
_backend_lock = threading.Lock()


def _select_backend() -> CredentialBackend:
    """Choose a backend from the bootstrap selector env (transport, not a secret)."""
    kind = os.environ.get("CONTEXTUAL_ORCHESTRATOR_KV_BACKEND", "memory").strip().lower()
    if kind in ("", "memory"):
        return InMemoryCredentialBackend()
    if kind == "postgres":
        return PostgresCredentialBackend.from_env()
    raise NotConfigured(f"unknown credential backend {kind!r}; expected 'memory' or 'postgres'")


def get_backend() -> CredentialBackend:
    """Return the process credential backend, creating it from bootstrap on first use."""
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = _select_backend()
    return _backend


def set_backend(backend: CredentialBackend | None) -> None:
    """Install (or, with ``None``, reset) the active credential backend.

    Used by bootstrap wiring and by tests to inject an in-memory backend.
    """
    global _backend
    with _backend_lock:
        _backend = backend


def get_credential(name: str) -> str | None:
    """Resolve a named runtime secret from the KV. Never reads os.getenv for it."""
    return get_backend().get(name)


def register_credential(name: str, value: str) -> None:
    """Register a named secret into the KV (used by the bootstrap CLI)."""
    get_backend().set(name, value)
