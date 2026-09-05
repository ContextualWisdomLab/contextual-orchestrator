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
  consistent with the org reference pattern while using semantic credential
  identifiers internally.

Backend selection is a bootstrap setting read from
``CONTEXTUAL_ORCHESTRATOR_KV_BACKEND`` (``memory`` default, or ``postgres``).
"""

from __future__ import annotations

from inspect import Parameter, Signature
import os
import threading
from typing import Any, Protocol, cast


class NotConfigured(RuntimeError):
    """Raised when a required credential cannot be resolved from the KV.

    This is deliberately distinct from a silent ``None``/env fallback: a
    non-mock agent whose credential is missing must fail loudly, never quietly
    read the environment.
    """


class CredentialBackend(Protocol):
    """Pluggable credential registry interface (a tiny KV of named secrets)."""

    def get(self, credential_name: str) -> str | None:
        """Return the secret for ``credential_name`` or ``None`` when absent."""
        ...

    def set(self, credential_name: str, credential_value: str) -> None:
        """Register or replace ``credential_value`` under ``credential_name``."""
        ...

    def delete(self, credential_name: str) -> None:
        """Remove one credential after an unvalidated candidate promotion."""
        ...


class InMemoryCredentialBackend:
    """Process-local credential registry for dev and tests (no Postgres needed)."""

    def __init__(self) -> None:
        self._credential_store: dict[str, str] = {}
        self._credential_lock = threading.Lock()

    def get(self, credential_name: str) -> str | None:
        """Return the in-memory secret for ``credential_name`` or ``None``."""
        with self._credential_lock:
            return self._credential_store.get(credential_name)

    def set(self, credential_name: str, credential_value: str) -> None:
        """Store ``credential_value`` under ``credential_name`` in memory."""
        with self._credential_lock:
            self._credential_store[credential_name] = credential_value

    def delete(self, credential_name: str) -> None:
        """Remove ``credential_name`` from the in-memory registry if present."""
        with self._credential_lock:
            self._credential_store.pop(credential_name, None)


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
        self._schema_ensured = False

    @property
    def connection_dsn(self) -> str:
        """Return the bootstrap DSN for a colocated metadata store.

        Callers must treat this as connection material: never include it in logs,
        reports, traces, or exceptions. Provider API keys remain inaccessible.
        """
        return self._dsn

    @classmethod
    def from_env(cls) -> PostgresCredentialBackend:
        """Build the backend from bootstrap transport env vars (the only allowed env use).

        ``CONTEXTUAL_ORCHESTRATOR_KV_DSN`` and
        ``CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`` open the encrypted KV; they are
        not runtime provider secrets.
        """
        return cls(
            dsn=os.environ.get("CONTEXTUAL_ORCHESTRATOR_KV_DSN", ""),
            passphrase=os.environ.get("CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE", ""),
        )

    def _connect(self):
        try:
            import psycopg
        except ImportError as import_failure:
            raise NotConfigured(
                "PostgresCredentialBackend needs the 'db' extra (psycopg); "
                "install contextual-orchestrator[db]"
            ) from import_failure
        return psycopg.connect(self._dsn)

    def _ensure_schema(self, database_connection) -> None:
        if self._schema_ensured:
            return
        with database_connection.cursor() as database_cursor:
            database_cursor.execute(CREATE_PROVIDER_CREDENTIALS_SQL)
        database_connection.commit()
        self._schema_ensured = True

    def get(self, credential_name: str) -> str | None:
        """Decrypt and return ``credential_name`` via pgcrypto, or ``None``."""
        with self._connect() as database_connection:
            self._ensure_schema(database_connection)
            with database_connection.cursor() as database_cursor:
                database_cursor.execute(
                    "SELECT pgp_sym_decrypt(encrypted_value, %s) "
                    "FROM provider_credentials WHERE credential_name = %s",
                    (self._passphrase, credential_name),
                )
                credential_row = database_cursor.fetchone()
        if credential_row is None:
            return None
        credential_value = credential_row[0]
        return (
            credential_value.decode("utf-8")
            if isinstance(credential_value, (bytes, bytearray))
            else credential_value
        )

    def set(self, credential_name: str, credential_value: str) -> None:
        """Encrypt and upsert ``credential_value`` under ``credential_name``."""
        with self._connect() as database_connection:
            self._ensure_schema(database_connection)
            with database_connection.cursor() as database_cursor:
                database_cursor.execute(
                    "INSERT INTO provider_credentials (credential_name, encrypted_value, updated_at) "
                    "VALUES (%s, pgp_sym_encrypt(%s, %s), now()) "
                    "ON CONFLICT (credential_name) DO UPDATE SET "
                    "encrypted_value = EXCLUDED.encrypted_value, updated_at = now()",
                    (credential_name, credential_value, self._passphrase),
                )
            database_connection.commit()

    def delete(
        self, credential_name: str
    ) -> None:  # pragma: no cover - requires a live Postgres
        """Delete one encrypted credential after a failed candidate promotion."""
        with self._connect() as database_connection:
            self._ensure_schema(database_connection)
            with database_connection.cursor() as database_cursor:
                database_cursor.execute(
                    "DELETE FROM provider_credentials WHERE credential_name = %s",
                    (credential_name,),
                )
            database_connection.commit()


_credential_backend: CredentialBackend | None = None
_credential_backend_lock = threading.Lock()
_MISSING_ARGUMENT: Any = object()


def _select_backend() -> CredentialBackend:
    """Choose a backend from the bootstrap selector env (transport, not a secret)."""
    backend_kind = os.environ.get("CONTEXTUAL_ORCHESTRATOR_KV_BACKEND", "memory").strip().lower()
    if backend_kind in ("", "memory"):
        return InMemoryCredentialBackend()
    if backend_kind == "postgres":
        return PostgresCredentialBackend.from_env()
    raise NotConfigured(
        f"unknown credential backend {backend_kind!r}; expected 'memory' or 'postgres'"
    )


def get_backend() -> CredentialBackend:
    """Return the process credential backend, creating it from bootstrap on first use."""
    global _credential_backend
    if _credential_backend is None:
        with _credential_backend_lock:
            if _credential_backend is None:
                _credential_backend = _select_backend()
    return _credential_backend


def _compatibility_argument(
    semantic_value: Any,
    semantic_name: str,
    legacy_name: str,
    compatibility_kwargs: dict[str, Any],
) -> Any:
    """Resolve one semantic argument from its bounded legacy keyword alias."""
    legacy_present = legacy_name in compatibility_kwargs
    if semantic_value is not _MISSING_ARGUMENT:
        if legacy_present:
            raise TypeError(
                f"{semantic_name} cannot be combined with legacy {legacy_name}"
            )
        return semantic_value
    if legacy_present:
        return compatibility_kwargs.pop(legacy_name)
    raise TypeError(f"missing required argument: {semantic_name}")


def _reject_unknown_compatibility_kwargs(compatibility_kwargs: dict[str, Any]) -> None:
    """Reject arbitrary kwargs instead of silently broadening the compatibility seam."""
    if compatibility_kwargs:
        unexpected_names = ", ".join(sorted(compatibility_kwargs))
        raise TypeError(f"unexpected keyword argument(s): {unexpected_names}")


def set_backend(
    credential_backend: CredentialBackend | None = _MISSING_ARGUMENT,
    **compatibility_kwargs: Any,
) -> None:
    """Install or reset the active credential backend through a semantic identifier."""
    resolved_credential_backend = _compatibility_argument(
        credential_backend,
        "credential_backend",
        "backend",
        compatibility_kwargs,
    )
    _reject_unknown_compatibility_kwargs(compatibility_kwargs)
    global _credential_backend
    with _credential_backend_lock:
        _credential_backend = cast(CredentialBackend | None, resolved_credential_backend)


def get_credential(
    credential_name: str = _MISSING_ARGUMENT,
    **compatibility_kwargs: Any,
) -> str | None:
    """Resolve a named runtime secret from the KV without runtime env fallback."""
    resolved_credential_name = _compatibility_argument(
        credential_name,
        "credential_name",
        "name",
        compatibility_kwargs,
    )
    _reject_unknown_compatibility_kwargs(compatibility_kwargs)
    return get_backend().get(cast(str, resolved_credential_name))


def register_credential(
    credential_name: str = _MISSING_ARGUMENT,
    credential_value: str = _MISSING_ARGUMENT,
    **compatibility_kwargs: Any,
) -> None:
    """Register a named secret into the KV through semantic public identifiers."""
    resolved_credential_name = _compatibility_argument(
        credential_name,
        "credential_name",
        "name",
        compatibility_kwargs,
    )
    resolved_credential_value = _compatibility_argument(
        credential_value,
        "credential_value",
        "value",
        compatibility_kwargs,
    )
    _reject_unknown_compatibility_kwargs(compatibility_kwargs)
    get_backend().set(
        cast(str, resolved_credential_name),
        cast(str, resolved_credential_value),
    )


def delete_credential(
    credential_name: str = _MISSING_ARGUMENT,
    **compatibility_kwargs: Any,
) -> None:
    """Remove a named credential through the semantic public identifier."""
    resolved_credential_name = _compatibility_argument(
        credential_name,
        "credential_name",
        "name",
        compatibility_kwargs,
    )
    _reject_unknown_compatibility_kwargs(compatibility_kwargs)
    get_backend().delete(cast(str, resolved_credential_name))


def _install_credential_public_signatures() -> None:
    """Expose required semantic names while runtime legacy aliases remain private."""
    semantic_name = Parameter(
        "credential_name",
        Parameter.POSITIONAL_OR_KEYWORD,
        annotation=str,
    )
    semantic_value = Parameter(
        "credential_value",
        Parameter.POSITIONAL_OR_KEYWORD,
        annotation=str,
    )
    semantic_backend = Parameter(
        "credential_backend",
        Parameter.POSITIONAL_OR_KEYWORD,
        annotation=CredentialBackend | None,
    )
    setattr(
        set_backend,
        "__signature__",
        Signature(parameters=[semantic_backend], return_annotation=None),
    )
    setattr(
        get_credential,
        "__signature__",
        Signature(parameters=[semantic_name], return_annotation=str | None),
    )
    setattr(
        register_credential,
        "__signature__",
        Signature(parameters=[semantic_name, semantic_value], return_annotation=None),
    )
    setattr(
        delete_credential,
        "__signature__",
        Signature(parameters=[semantic_name], return_annotation=None),
    )


_install_credential_public_signatures()
