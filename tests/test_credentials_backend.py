"""Postgres credential-backend construction + bootstrap selection.

Covers the non-DB surface of ``credentials.py``: ``PostgresCredentialBackend``
argument validation, ``from_env`` bootstrap-transport reads, and the
``_select_backend`` postgres branch. The live pgcrypto/psycopg methods
(``_connect``/``get``/``set``) require a real Postgres and stay
``# pragma: no cover``. No Postgres is needed for any test here.

These pin the org "KV, not env" invariant at its bootstrap boundary: the DSN
and passphrase are the only permitted environment reads, and a missing one must
fail loudly (``NotConfigured``) rather than degrade to a silent/empty backend.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    NotConfigured,
    PostgresCredentialBackend,
    _select_backend,
)

_DSN_ENV = "CONTEXTUAL_ORCHESTRATOR_KV_DSN"
_PASS_ENV = "CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE"
_BACKEND_ENV = "CONTEXTUAL_ORCHESTRATOR_KV_BACKEND"


def test_postgres_backend_requires_dsn() -> None:
    """An empty bootstrap DSN fails loudly instead of building a broken backend."""
    with pytest.raises(NotConfigured):
        PostgresCredentialBackend("", "passphrase")


def test_postgres_backend_requires_passphrase() -> None:
    """An empty bootstrap passphrase fails loudly."""
    with pytest.raises(NotConfigured):
        PostgresCredentialBackend("postgresql://localhost/db", "")


def test_postgres_backend_stores_bootstrap_transport() -> None:
    """A valid DSN + passphrase construct a backend that has not yet touched the DB."""
    backend = PostgresCredentialBackend("postgresql://localhost/db", "s3cret")
    assert backend._dsn == "postgresql://localhost/db"
    assert backend._passphrase == "s3cret"
    assert backend._ensured is False  # schema is ensured lazily on first connect


def test_from_env_reads_only_bootstrap_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """``from_env`` builds the backend from the two bootstrap-transport env vars."""
    monkeypatch.setenv(_DSN_ENV, "postgresql://kv-host/registry")
    monkeypatch.setenv(_PASS_ENV, "unlock-phrase")
    backend = PostgresCredentialBackend.from_env()
    assert isinstance(backend, PostgresCredentialBackend)
    assert backend._dsn == "postgresql://kv-host/registry"
    assert backend._passphrase == "unlock-phrase"


def test_from_env_missing_dsn_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the DSN env unset, ``from_env`` surfaces ``NotConfigured`` (no silent empty backend)."""
    monkeypatch.delenv(_DSN_ENV, raising=False)
    monkeypatch.setenv(_PASS_ENV, "unlock-phrase")
    with pytest.raises(NotConfigured):
        PostgresCredentialBackend.from_env()


def test_select_backend_defaults_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset/`memory` selector yields the dependency-free in-memory backend."""
    monkeypatch.delenv(_BACKEND_ENV, raising=False)
    assert isinstance(_select_backend(), InMemoryCredentialBackend)
    monkeypatch.setenv(_BACKEND_ENV, "MEMORY")  # case-insensitive
    assert isinstance(_select_backend(), InMemoryCredentialBackend)


def test_select_backend_postgres_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``postgres`` selector routes through ``from_env`` to a Postgres backend."""
    monkeypatch.setenv(_BACKEND_ENV, "postgres")
    monkeypatch.setenv(_DSN_ENV, "postgresql://kv-host/registry")
    monkeypatch.setenv(_PASS_ENV, "unlock-phrase")
    backend = _select_backend()
    assert isinstance(backend, PostgresCredentialBackend)


def test_select_backend_unknown_selector_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognized selector fails loudly rather than guessing a backend."""
    monkeypatch.setenv(_BACKEND_ENV, "vault")
    with pytest.raises(NotConfigured):
        _select_backend()
