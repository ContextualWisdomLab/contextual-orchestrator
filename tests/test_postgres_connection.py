"""PostgreSQL driver-boundary tests."""

import ssl
import subprocess
import sys
from inspect import signature

import pytest

from contextual_orchestrator.postgres_connection import connect_pg8000


def test_base_import_does_not_require_sqlalchemy() -> None:
    """Keep the in-memory credential path importable without the database extra."""
    script = """
import builtins
real_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == 'sqlalchemy' or name.startswith('sqlalchemy.'):
        raise ModuleNotFoundError(name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked
from contextual_orchestrator.credentials import InMemoryCredentialBackend
assert InMemoryCredentialBackend
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_connect_pg8000_preserves_url_options(monkeypatch) -> None:
    """Select pg8000 while preserving credentials, catalog, and query options."""
    connection = object()
    captured: dict[str, object] = {}

    from pg8000 import dbapi

    real_connect = dbapi.connect

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return connection

    monkeypatch.setattr("pg8000.dbapi.connect", fake_connect)

    assert (
        connect_pg8000(
            "postgresql://catalog_user:secret@db.example:5433/catalog?sslmode=require"
        )
        is connection
    )
    assert captured["user"] == "catalog_user"
    assert captured["password"] == "secret"
    assert captured["host"] == "db.example"
    assert captured["port"] == 5433
    assert captured["database"] == "catalog"
    context = captured["ssl_context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE
    signature(real_connect).bind(**captured)


def test_connect_pg8000_preserves_quoted_keyword_dsn_socket_and_timeout(
    monkeypatch,
) -> None:
    """Preserve libpq keyword quoting plus socket and timeout behavior."""
    captured: dict[str, object] = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("pg8000.dbapi.connect", fake_connect)
    connect_pg8000(
        "host=/var/run/postgresql dbname='catalog db' user=alice "
        "password='space secret' connect_timeout=2 application_name=orchestrator"
    )
    assert captured == {
        "application_name": "orchestrator",
        "database": "catalog db",
        "password": "space secret",
        "ssl_context": None,
        "timeout": 2.0,
        "unix_sock": "/var/run/postgresql/.s.PGSQL.5432",
        "user": "alice",
    }


def test_keyword_dsn_matches_libpq_spacing_escaping_and_embedded_scheme(
    monkeypatch,
) -> None:
    """Accept libpq grammar without treating a value containing :// as a URI."""
    captured: dict[str, object] = {}
    monkeypatch.setattr("pg8000.dbapi.connect", lambda **kwargs: captured.update(kwargs))

    connect_pg8000(
        r"user = alice dbname = catalog password='it\'s\\safe' "
        r"application_name='https://example.invalid/a b'"
    )

    assert captured["user"] == "alice"
    assert captured["database"] == "catalog"
    assert captured["password"] == "it's\\safe"
    assert captured["application_name"] == "https://example.invalid/a b"


def test_url_timeout_uses_pg8000_timeout(monkeypatch) -> None:
    """Translate documented URI connect_timeout through the common path."""
    captured: dict[str, object] = {}
    monkeypatch.setattr("pg8000.dbapi.connect", lambda **kwargs: captured.update(kwargs))

    connect_pg8000("postgresql://alice@db.example/catalog?connect_timeout=2")

    assert captured["timeout"] == 2.0


def test_require_with_root_certificate_verifies_ca(monkeypatch) -> None:
    """Honor libpq's require-plus-root-certificate compatibility behavior."""
    captured: dict[str, object] = {}
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    monkeypatch.setattr(ssl, "create_default_context", lambda *, cafile=None: context)
    monkeypatch.setattr("pg8000.dbapi.connect", lambda **kwargs: captured.update(kwargs))

    connect_pg8000(
        "postgresql://alice@db.example/catalog?sslmode=require&sslrootcert=/ca.pem"
    )

    assert captured["ssl_context"] is context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is False


def test_client_certificate_without_explicit_sslmode_is_consumed(monkeypatch) -> None:
    """Treat libpq client certificate parameters independently from sslmode."""
    captured: dict[str, object] = {}
    loaded: list[tuple[str, str | None]] = []

    class _Context:
        check_hostname = True

        def load_cert_chain(self, cert: str, keyfile: str | None = None) -> None:
            loaded.append((cert, keyfile))

    context = _Context()
    monkeypatch.setattr(ssl, "SSLContext", lambda _protocol: context)
    monkeypatch.setattr("pg8000.dbapi.connect", lambda **kwargs: captured.update(kwargs))

    connect_pg8000(
        "postgresql://alice@db.example/catalog?sslcert=/client.pem&sslkey=/client.key"
    )

    assert captured["ssl_context"] is context
    assert loaded == [("/client.pem", "/client.key")]


def test_connect_pg8000_preserves_connection_error(monkeypatch) -> None:
    """Do not relabel a live connection failure as a missing dependency."""
    failure = OSError("connection refused")

    def fail_connect(**_kwargs):
        raise failure

    monkeypatch.setattr("pg8000.dbapi.connect", fail_connect)
    with pytest.raises(OSError) as caught:
        connect_pg8000("postgresql://alice@db.example/catalog")
    assert caught.value is failure
