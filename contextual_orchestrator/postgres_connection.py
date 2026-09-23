"""Shared PostgreSQL connection factory using the permissively licensed driver."""

from __future__ import annotations

from typing import Any


def connect_pg8000(dsn: str) -> Any:
    """Open a DB-API connection while preserving PostgreSQL URL options."""
    try:
        import pg8000  # noqa: F401 -- fail here with actionable optional-extra guidance
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url
        from sqlalchemy.pool import NullPool
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL support needs the 'db' extra (pg8000); "
            "install contextual-orchestrator[db]"
        ) from exc

    url = make_url(dsn).set(drivername="postgresql+pg8000")
    engine = create_engine(url, poolclass=NullPool)
    try:
        return engine.raw_connection()
    except BaseException:
        engine.dispose()
        raise
