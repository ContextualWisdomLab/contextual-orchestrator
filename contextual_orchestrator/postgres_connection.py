"""Shared PostgreSQL connection factory using the permissively licensed driver."""

from __future__ import annotations

import shlex
import ssl
from typing import Any

from sqlalchemy.engine import make_url


class PostgresDriverUnavailable(RuntimeError):
    """Raised only when the optional PostgreSQL driver is not installed."""


def _keyword_dsn(dsn: str) -> dict[str, str]:
    """Parse libpq's quoted ``key=value`` connection-string form."""
    try:
        tokens = shlex.split(dsn, comments=False, posix=True)
    except ValueError as exc:
        raise ValueError("invalid quoted PostgreSQL DSN") from exc
    values: dict[str, str] = {}
    for token in tokens:
        key, separator, value = token.partition("=")
        if not separator or not key:
            raise ValueError("invalid PostgreSQL keyword DSN")
        values[key] = value
    return values


def _ssl_context(options: dict[str, str]) -> ssl.SSLContext | bool | None:
    """Translate supported libpq TLS requirements without weakening verification."""
    mode = options.pop("sslmode", None)
    if mode is None:
        return None
    if mode == "disable":
        return False
    if mode == "require":
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    elif mode in {"verify-ca", "verify-full"}:
        context = ssl.create_default_context(cafile=options.pop("sslrootcert", None))
        context.check_hostname = mode == "verify-full"
    else:
        raise ValueError(f"unsupported pg8000 sslmode: {mode}")
    certificate = options.pop("sslcert", None)
    key = options.pop("sslkey", None)
    if certificate is not None:
        context.load_cert_chain(certificate, keyfile=key)
    elif key is not None:
        raise ValueError("sslkey requires sslcert")
    return context


def _connect_options(dsn: str) -> dict[str, Any]:
    """Normalize URL and libpq keyword DSNs to pg8000's explicit API."""
    if "://" in dsn:
        url = make_url(dsn)
        if url.drivername not in {"postgres", "postgresql", "postgresql+pg8000"}:
            raise ValueError("PostgreSQL DSN must use postgres or postgresql")
        options: dict[str, Any] = dict(url.query)
        translated = url.translate_connect_args(username="user", database="database")
        options.update({key: value for key, value in translated.items() if value is not None})
    else:
        options = _keyword_dsn(dsn)
        if "dbname" in options:
            options["database"] = options.pop("dbname")
        if "connect_timeout" in options:
            options["timeout"] = float(options.pop("connect_timeout"))
        if "host" in options and options["host"].startswith("/"):
            socket_directory = options.pop("host")
            socket_port = int(options.get("port", 5432))
            options["unix_sock"] = f"{socket_directory}/.s.PGSQL.{socket_port}"

    options["ssl_context"] = _ssl_context(options)
    allowed = {
        "application_name",
        "database",
        "host",
        "password",
        "port",
        "ssl_context",
        "timeout",
        "unix_sock",
        "user",
    }
    unsupported = sorted(set(options) - allowed)
    if unsupported:
        raise ValueError(f"unsupported pg8000 connection options: {', '.join(unsupported)}")
    if "port" in options:
        options["port"] = int(options["port"])
    return options


def connect_pg8000(dsn: str) -> Any:
    """Open a pg8000 DB-API connection from a URL or libpq keyword DSN."""
    try:
        from pg8000 import dbapi
    except ImportError as exc:
        raise PostgresDriverUnavailable(
            "PostgreSQL support needs the 'db' extra (pg8000); "
            "install contextual-orchestrator[db]"
        ) from exc
    return dbapi.connect(**_connect_options(dsn))
