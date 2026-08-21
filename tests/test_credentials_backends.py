"""Credential backends preserve the encrypted KV trust boundary."""

from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace
from typing import Self
from unittest.mock import Mock, patch

import pytest

from contextual_orchestrator import credentials
from contextual_orchestrator.credentials import (
    CREATE_PROVIDER_CREDENTIALS_SQL,
    InMemoryCredentialBackend,
    NotConfigured,
    PostgresCredentialBackend,
)


class _Cursor:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[str, ...] = ()) -> None:
        self._connection.executions.append((statement, params))

    def fetchone(self):
        return self._connection.rows.pop(0)


class _Connection:
    def __init__(self, rows: list[tuple[str | bytes] | None] | None = None) -> None:
        self.rows = list(rows or [])
        self.executions: list[tuple[str, tuple[str, ...]]] = []
        self.commit_count = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.commit_count += 1


@pytest.fixture(autouse=True)
def _isolated_backend(monkeypatch: pytest.MonkeyPatch):
    """Reset the process registry and bootstrap transport around every test."""
    credentials.set_backend(None)
    for name in (
        "CONTEXTUAL_ORCHESTRATOR_KV_BACKEND",
        "CONTEXTUAL_ORCHESTRATOR_KV_DSN",
        "CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    credentials.set_backend(None)


@pytest.mark.parametrize(
    ("dsn", "passphrase", "message"),
    [
        ("", "bootstrap-passphrase", "bootstrap DSN"),
        ("postgresql://db.example/credential_store", "", "bootstrap passphrase"),
    ],
)
def test_postgres_backend_requires_both_bootstrap_values(
    dsn: str,
    passphrase: str,
    message: str,
) -> None:
    """Fail closed before a database call when bootstrap transport is incomplete."""
    with pytest.raises(NotConfigured, match=message):
        PostgresCredentialBackend(dsn, passphrase)


@pytest.mark.parametrize("selector", [None, "", " MEMORY "])
def test_memory_selector_uses_the_process_local_backend(
    monkeypatch: pytest.MonkeyPatch,
    selector: str | None,
) -> None:
    """Keep memory as the explicit and default development backend."""
    if selector is not None:
        monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_KV_BACKEND", selector)

    assert isinstance(credentials.get_backend(), InMemoryCredentialBackend)


def test_postgres_selector_reads_only_bootstrap_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build Postgres from the DSN and passphrase without reading provider keys."""
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_KV_BACKEND", "POSTGRES")
    monkeypatch.setenv(
        "CONTEXTUAL_ORCHESTRATOR_KV_DSN",
        "postgresql://db.example/credential_store",
    )
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE", "bootstrap-passphrase")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-read")

    backend = credentials.get_backend()

    assert isinstance(backend, PostgresCredentialBackend)
    assert backend._dsn == "postgresql://db.example/credential_store"
    assert backend._passphrase == "bootstrap-passphrase"


def test_get_backend_handles_another_thread_winning_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return the backend installed between the outer and locked checks."""
    winner = InMemoryCredentialBackend()

    class _WinningLock:
        def __enter__(self) -> None:
            credentials._backend = winner

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(credentials, "_backend_lock", _WinningLock())

    assert credentials.get_backend() is winner


def test_psycopg_connection_uses_only_the_bootstrap_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass the configured DSN to psycopg without reconstructing a connection URL."""
    connection = object()
    connect = Mock(return_value=connection)
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    backend = PostgresCredentialBackend(
        "postgresql://db.example/credential_store",
        "bootstrap-passphrase",
    )

    assert backend._connect() is connection
    connect.assert_called_once_with("postgresql://db.example/credential_store")


def test_missing_psycopg_extra_fails_with_install_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explain the optional database dependency instead of leaking ImportError."""
    real_import = builtins.__import__

    def import_without_psycopg(name: str, *args: object, **kwargs: object):
        if name == "psycopg":
            raise ImportError("synthetic missing optional dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_psycopg)
    backend = PostgresCredentialBackend("postgresql://db.example/store", "passphrase")

    with pytest.raises(NotConfigured, match="db.*psycopg"):
        backend._connect()


def test_postgres_get_decrypts_bytes_and_preserves_text() -> None:
    """Return missing, byte, and text values while preparing the schema only once."""
    connection = _Connection([None, (b"synthetic-secret",), ("synthetic-text",)])
    backend = PostgresCredentialBackend("postgresql://db.example/store", "passphrase")

    with patch.object(backend, "_connect", return_value=connection):
        assert backend.get("missing_credential") is None
        assert backend.get("byte_credential") == "synthetic-secret"
        assert backend.get("text_credential") == "synthetic-text"

    schema_calls = [call for call in connection.executions if call[0] == CREATE_PROVIDER_CREDENTIALS_SQL]
    select_calls = [call for call in connection.executions if call[0].startswith("SELECT")]
    assert len(schema_calls) == 1
    assert [params for _statement, params in select_calls] == [
        ("passphrase", "missing_credential"),
        ("passphrase", "byte_credential"),
        ("passphrase", "text_credential"),
    ]
    assert connection.commit_count == 1


def test_postgres_set_encrypts_and_upserts_without_plaintext_columns() -> None:
    """Use pgcrypto parameters and one normalized upsert for create and replace."""
    connection = _Connection()
    backend = PostgresCredentialBackend("postgresql://db.example/store", "passphrase")

    with patch.object(backend, "_connect", return_value=connection):
        backend.set("provider_api_key", "synthetic-value-one")
        backend.set("provider_api_key", "synthetic-value-two")

    schema_calls = [call for call in connection.executions if call[0] == CREATE_PROVIDER_CREDENTIALS_SQL]
    upsert_calls = [call for call in connection.executions if call[0].startswith("INSERT")]
    assert len(schema_calls) == 1
    assert "pgp_sym_encrypt" in upsert_calls[0][0]
    assert "ON CONFLICT (credential_name)" in upsert_calls[0][0]
    assert [params for _statement, params in upsert_calls] == [
        ("provider_api_key", "synthetic-value-one", "passphrase"),
        ("provider_api_key", "synthetic-value-two", "passphrase"),
    ]
    assert connection.commit_count == 3
