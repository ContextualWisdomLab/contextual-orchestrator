"""PostgreSQL driver-boundary tests."""

from types import SimpleNamespace

from contextual_orchestrator.postgres_connection import connect_pg8000


def test_connect_pg8000_preserves_url_options(monkeypatch) -> None:
    """Select pg8000 while preserving credentials, catalog, and query options."""
    connection = object()
    engine = SimpleNamespace(raw_connection=lambda: connection, dispose=lambda: None)
    captured: dict[str, object] = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return engine

    monkeypatch.setattr("sqlalchemy.create_engine", fake_create_engine)

    assert (
        connect_pg8000(
            "postgresql://catalog_user:secret@db.example:5433/catalog?sslmode=require"
        )
        is connection
    )
    url = captured["url"]
    assert url.drivername == "postgresql+pg8000"
    assert url.username == "catalog_user"
    assert url.database == "catalog"
    assert url.query == {"sslmode": "require"}
