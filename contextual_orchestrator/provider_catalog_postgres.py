"""PostgreSQL persistence adapter for the durable provider catalog.

The adapter stores provider-account and model metadata only. Provider values
remain in the separate pgcrypto credential registry and are referenced by stable
credential names.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import threading
from typing import Any, Sequence

from .provider_catalog import (
    CatalogModelRecord,
    DiscoveredModel,
    ProviderAccount,
    ProviderCatalogUnavailable,
)


PROVIDER_CATALOG_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS provider_accounts (
    provider_account_id text PRIMARY KEY,
    provider_name text NOT NULL,
    credential_name text NOT NULL,
    base_url text NOT NULL,
    models_path text,
    transport_name text NOT NULL,
    auth_header_name text NOT NULL,
    auth_prefix text NOT NULL,
    enabled_flag boolean NOT NULL DEFAULT true,
    priority_rank integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_models (
    provider_model_id text PRIMARY KEY,
    provider_account_id text NOT NULL REFERENCES provider_accounts(provider_account_id),
    model_name text NOT NULL,
    display_name text NOT NULL,
    context_window integer,
    input_price_usd_per_million numeric(20, 8),
    output_price_usd_per_million numeric(20, 8),
    enabled_flag boolean NOT NULL DEFAULT true,
    first_discovered_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    UNIQUE (provider_account_id, model_name)
);

CREATE TABLE IF NOT EXISTS model_capabilities (
    provider_model_id text NOT NULL REFERENCES provider_models(provider_model_id) ON DELETE CASCADE,
    capability_name text NOT NULL,
    PRIMARY KEY (provider_model_id, capability_name)
);

CREATE TABLE IF NOT EXISTS model_modalities (
    provider_model_id text NOT NULL REFERENCES provider_models(provider_model_id) ON DELETE CASCADE,
    modality_name text NOT NULL,
    PRIMARY KEY (provider_model_id, modality_name)
);

CREATE TABLE IF NOT EXISTS catalog_refresh_runs (
    catalog_refresh_id text PRIMARY KEY,
    provider_account_id text NOT NULL REFERENCES provider_accounts(provider_account_id),
    refresh_status text NOT NULL,
    observed_model_count integer NOT NULL DEFAULT 0,
    error_code text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS provider_models_account_idx
    ON provider_models (provider_account_id, enabled_flag);
CREATE INDEX IF NOT EXISTS catalog_refresh_account_idx
    ON catalog_refresh_runs (provider_account_id, finished_at DESC);
"""
"""Third-normal-form catalog schema containing no provider-secret values."""


class PostgresProviderCatalogStore:  # pragma: no cover - requires live PostgreSQL
    """Normalized PostgreSQL provider catalog with account-scoped transactions."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ProviderCatalogUnavailable("provider catalog requires a PostgreSQL DSN")
        self._dsn = dsn
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise ProviderCatalogUnavailable(
                "provider catalog requires contextual-orchestrator[db]"
            ) from exc
        return psycopg.connect(self._dsn)

    def _ensure_schema(self, connection: Any) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with connection.cursor() as cursor:
                cursor.execute(PROVIDER_CATALOG_SCHEMA_SQL)
            connection.commit()
            self._schema_ready = True

    def upsert_account(self, account: ProviderAccount) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                _upsert_account_row(cursor, account)
            connection.commit()

    def replace_catalog(self, account: ProviderAccount, models: Sequence[DiscoveredModel]) -> None:
        started_at = _utc_now()
        unique = {model.model_name: model for model in models if model.model_name}
        with self._connect() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                _upsert_account_row(cursor, account)
                seen_ids: list[str] = []
                for model in unique.values():
                    model_id = _provider_model_id(account.provider_account_id, model.model_name)
                    seen_ids.append(model_id)
                    cursor.execute(
                        "INSERT INTO provider_models ("
                        "provider_model_id, provider_account_id, model_name, display_name, "
                        "context_window, input_price_usd_per_million, output_price_usd_per_million, "
                        "enabled_flag, first_discovered_at, last_seen_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s, %s) "
                        "ON CONFLICT (provider_model_id) DO UPDATE SET "
                        "display_name = EXCLUDED.display_name, context_window = EXCLUDED.context_window, "
                        "input_price_usd_per_million = EXCLUDED.input_price_usd_per_million, "
                        "output_price_usd_per_million = EXCLUDED.output_price_usd_per_million, "
                        "enabled_flag = true, last_seen_at = EXCLUDED.last_seen_at",
                        (
                            model_id,
                            account.provider_account_id,
                            model.model_name,
                            model.display_name,
                            model.context_window,
                            model.input_price_usd_per_million,
                            model.output_price_usd_per_million,
                            started_at,
                            started_at,
                        ),
                    )
                    cursor.execute(
                        "DELETE FROM model_capabilities WHERE provider_model_id = %s",
                        (model_id,),
                    )
                    cursor.execute(
                        "DELETE FROM model_modalities WHERE provider_model_id = %s",
                        (model_id,),
                    )
                    for capability in model.capabilities:
                        cursor.execute(
                            "INSERT INTO model_capabilities (provider_model_id, capability_name) "
                            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                            (model_id, capability),
                        )
                    for modality in model.modalities:
                        cursor.execute(
                            "INSERT INTO model_modalities (provider_model_id, modality_name) "
                            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                            (model_id, modality),
                        )
                if seen_ids:
                    cursor.execute(
                        "UPDATE provider_models SET enabled_flag = false "
                        "WHERE provider_account_id = %s AND NOT (provider_model_id = ANY(%s))",
                        (account.provider_account_id, seen_ids),
                    )
                else:
                    cursor.execute(
                        "UPDATE provider_models SET enabled_flag = false "
                        "WHERE provider_account_id = %s",
                        (account.provider_account_id,),
                    )
                _insert_refresh_row(
                    cursor,
                    account.provider_account_id,
                    "refreshed",
                    len(unique),
                    None,
                    started_at,
                    _utc_now(),
                )
            connection.commit()

    def record_failure(self, account: ProviderAccount, error_code: str) -> None:
        started_at = _utc_now()
        with self._connect() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                _upsert_account_row(cursor, account)
                _insert_refresh_row(
                    cursor,
                    account.provider_account_id,
                    "failed",
                    0,
                    error_code,
                    started_at,
                    _utc_now(),
                )
            connection.commit()

    def enabled_models(self) -> list[CatalogModelRecord]:
        return self._read_models(enabled_accounts_only=True)

    def all_models(self) -> list[CatalogModelRecord]:
        return self._read_models(enabled_accounts_only=False)

    def has_models(self, provider_account_id: str) -> bool:
        with self._connect() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM provider_models "
                    "WHERE provider_account_id = %s AND enabled_flag = true)",
                    (provider_account_id,),
                )
                row = cursor.fetchone()
        return bool(row and row[0])

    def _read_models(self, *, enabled_accounts_only: bool) -> list[CatalogModelRecord]:
        if enabled_accounts_only:
            query = (
                "SELECT m.provider_account_id, m.provider_model_id, m.model_name, "
                "m.display_name, m.context_window, m.input_price_usd_per_million, "
                "m.output_price_usd_per_million "
                "FROM provider_models m JOIN provider_accounts a "
                "ON a.provider_account_id = m.provider_account_id "
                "WHERE m.enabled_flag = true AND a.enabled_flag = true "
                "ORDER BY m.provider_account_id, m.model_name"
            )
        else:
            query = (
                "SELECT m.provider_account_id, m.provider_model_id, m.model_name, "
                "m.display_name, m.context_window, m.input_price_usd_per_million, "
                "m.output_price_usd_per_million "
                "FROM provider_models m JOIN provider_accounts a "
                "ON a.provider_account_id = m.provider_account_id "
                "WHERE m.enabled_flag = true "
                "ORDER BY m.provider_account_id, m.model_name"
            )
        with self._connect() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
                records: list[CatalogModelRecord] = []
                for row in rows:
                    cursor.execute(
                        "SELECT capability_name FROM model_capabilities "
                        "WHERE provider_model_id = %s ORDER BY capability_name",
                        (row[1],),
                    )
                    capabilities = tuple(item[0] for item in cursor.fetchall())
                    cursor.execute(
                        "SELECT modality_name FROM model_modalities "
                        "WHERE provider_model_id = %s ORDER BY modality_name",
                        (row[1],),
                    )
                    modalities = tuple(item[0] for item in cursor.fetchall())
                    records.append(
                        CatalogModelRecord(
                            row[0],
                            DiscoveredModel(
                                model_name=row[2],
                                display_name=row[3],
                                capabilities=capabilities,
                                modalities=modalities,
                                context_window=row[4],
                                input_price_usd_per_million=_optional_float(row[5]),
                                output_price_usd_per_million=_optional_float(row[6]),
                            ),
                        )
                    )
        return records


def _upsert_account_row(cursor: Any, account: ProviderAccount) -> None:  # pragma: no cover
    """Execute the parameter-bound provider-account upsert."""
    cursor.execute(
        "INSERT INTO provider_accounts ("
        "provider_account_id, provider_name, credential_name, base_url, models_path, "
        "transport_name, auth_header_name, auth_prefix, enabled_flag, priority_rank, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
        "ON CONFLICT (provider_account_id) DO UPDATE SET "
        "provider_name = EXCLUDED.provider_name, credential_name = EXCLUDED.credential_name, "
        "base_url = EXCLUDED.base_url, models_path = EXCLUDED.models_path, "
        "transport_name = EXCLUDED.transport_name, auth_header_name = EXCLUDED.auth_header_name, "
        "auth_prefix = EXCLUDED.auth_prefix, enabled_flag = EXCLUDED.enabled_flag, "
        "priority_rank = EXCLUDED.priority_rank, updated_at = now()",
        (
            account.provider_account_id,
            account.provider_name,
            account.credential_name,
            account.base_url,
            account.models_path,
            account.transport_name,
            account.auth_header_name,
            account.auth_prefix,
            account.enabled,
            account.priority_rank,
        ),
    )


def _insert_refresh_row(  # pragma: no cover
    cursor: Any,
    account_id: str,
    status: str,
    count: int,
    error_code: str | None,
    started_at: datetime,
    finished_at: datetime,
) -> None:
    """Insert one immutable provider refresh evidence row."""
    cursor.execute(
        "INSERT INTO catalog_refresh_runs ("
        "catalog_refresh_id, provider_account_id, refresh_status, observed_model_count, "
        "error_code, started_at, finished_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            _refresh_id(account_id, finished_at.isoformat()),
            account_id,
            status,
            count,
            error_code,
            started_at,
            finished_at,
        ),
    )


def _provider_model_id(provider_account_id: str, model_name: str) -> str:  # pragma: no cover
    """Return a stable non-secret identifier for one account/model pair."""
    material = f"{provider_account_id}\0{model_name}".encode("utf-8")
    return f"provider_model_{hashlib.sha256(material).hexdigest()}"


def _refresh_id(account_id: str, timestamp: str) -> str:  # pragma: no cover
    """Return an immutable catalog refresh identifier."""
    material = f"{account_id}\0{timestamp}".encode("utf-8")
    return f"catalog_refresh_{hashlib.sha256(material).hexdigest()}"


def _optional_float(value: Any) -> float | None:  # pragma: no cover
    """Convert one finite database numeric value to float, preserving null."""
    if value is None:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _utc_now() -> datetime:  # pragma: no cover
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)
