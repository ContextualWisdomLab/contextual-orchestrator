"""PostgreSQL driver-boundary tests."""

import ssl
from inspect import signature

import pytest

from contextual_orchestrator.postgres_connection import connect_pg8000


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


def test_connect_pg8000_preserves_connection_error(monkeypatch) -> None:
    """Do not relabel a live connection failure as a missing dependency."""
    failure = OSError("connection refused")

    def fail_connect(**_kwargs):
        raise failure

    monkeypatch.setattr("pg8000.dbapi.connect", fail_connect)
    with pytest.raises(OSError) as caught:
        connect_pg8000("postgresql://alice@db.example/catalog")
    assert caught.value is failure
