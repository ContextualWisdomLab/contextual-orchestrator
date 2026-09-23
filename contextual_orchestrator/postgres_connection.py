"""Shared PostgreSQL connection factory using the permissively licensed driver."""

from __future__ import annotations

import re
import ssl
from typing import Any


class PostgresDriverUnavailable(RuntimeError):
    """Raised only when the optional PostgreSQL driver is not installed."""


def _keyword_dsn(dsn: str) -> dict[str, str]:
    """Parse libpq's quoted ``key=value`` connection-string form."""
    values: dict[str, str] = {}
    position = 0
    while position < len(dsn):
        while position < len(dsn) and dsn[position].isspace():
            position += 1
        if position == len(dsn):
            break
        key_start = position
        while (
            position < len(dsn)
            and not dsn[position].isspace()
            and dsn[position] != "="
        ):
            position += 1
        key = dsn[key_start:position]
        while position < len(dsn) and dsn[position].isspace():
            position += 1
        if not key or position == len(dsn) or dsn[position] != "=":
            raise ValueError("invalid PostgreSQL keyword DSN")
        position += 1
        while position < len(dsn) and dsn[position].isspace():
            position += 1
        value: list[str] = []
        quoted = position < len(dsn) and dsn[position] == "'"
        if quoted:
            position += 1
        closed = not quoted
        while position < len(dsn):
            character = dsn[position]
            if character == "\\":
                position += 1
                if position == len(dsn):
                    raise ValueError("invalid quoted PostgreSQL DSN")
                value.append(dsn[position])
                position += 1
                continue
            if quoted and character == "'":
                position += 1
                closed = True
                break
            if not quoted and character.isspace():
                break
            value.append(character)
            position += 1
        if not closed:
            raise ValueError("invalid quoted PostgreSQL DSN")
        if position < len(dsn) and not dsn[position].isspace():
            raise ValueError("invalid PostgreSQL keyword DSN")
        values[key] = "".join(value)
    return values


def _ssl_context(options: dict[str, str]) -> ssl.SSLContext | bool | None:
    """Translate supported libpq TLS requirements without weakening verification."""
    mode = options.pop("sslmode", None)
    root_certificate = options.pop("sslrootcert", None)
    certificate = options.pop("sslcert", None)
    key = options.pop("sslkey", None)
    if key is not None and certificate is None:
        raise ValueError("sslkey requires sslcert")
    if mode is None and root_certificate is None and certificate is None:
        return None
    if mode == "disable":
        if root_certificate is not None or certificate is not None:
            raise ValueError("sslmode=disable cannot use TLS certificate options")
        return False
    if mode in {None, "require"} and root_certificate is None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    elif mode in {None, "require", "verify-ca", "verify-full"}:
        context = ssl.create_default_context(cafile=root_certificate)
        context.check_hostname = mode == "verify-full"
    else:
        raise ValueError(f"unsupported pg8000 sslmode: {mode}")
    if certificate is not None:
        context.load_cert_chain(certificate, keyfile=key)
    return context


def _connect_options(dsn: str) -> dict[str, Any]:
    """Normalize URL and libpq keyword DSNs to pg8000's explicit API."""
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", dsn):
        from sqlalchemy.engine import make_url

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
        if "host" in options and options["host"].startswith("/"):
            socket_directory = options.pop("host")
            socket_port = int(options.get("port", 5432))
            options["unix_sock"] = f"{socket_directory}/.s.PGSQL.{socket_port}"

    if "connect_timeout" in options:
        options["timeout"] = float(options.pop("connect_timeout"))
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
