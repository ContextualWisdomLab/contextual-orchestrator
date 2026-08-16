"""Durable provider discovery, catalog persistence, and agent-pool construction.

The module turns deploy-time provider credentials into a runtime model pool
without making raw environment variables the request-time source of secrets.
GitHub Actions or another trusted bootstrap process may transport the fixed
credential inventory into :mod:`contextual_orchestrator.credentials`; runtime
provider calls resolve only the credential *name* from that registry.

Provider metadata is kept separately from credential values in a normalized
catalog. A failed refresh never deletes the last-known-good catalog, while a
first deployment with no usable model fails closed instead of silently falling
back to a mock worker.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import http.client
import ipaddress
import json
import math
import os
import random
import re
import socket
import ssl
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence
from urllib.parse import urlparse

from .credentials import get_credential, register_credential
from .orchestrator import ModelAgent, ModelClient, TaskOrchestrator


CATALOG_RESPONSE_MAX_BYTES = 8 * 1024 * 1024
"""Maximum accepted bytes in one provider model-catalog response."""

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
"""Normalized PostgreSQL schema for provider accounts, models, and refresh evidence."""


@dataclass(frozen=True)
class ProviderAccount:
    """One independently governed provider account and credential reference."""

    provider_account_id: str
    provider_name: str
    credential_name: str
    base_url: str
    models_path: str | None = "/models"
    transport_name: str = "openai_compatible"
    auth_header_name: str = "Authorization"
    auth_prefix: str = "Bearer"
    enabled: bool = True
    priority_rank: int = 0

    @property
    def models_url(self) -> str | None:
        """Return the complete model-list endpoint, or ``None`` when unsupported."""
        if not self.models_path:
            return None
        return f"{self.base_url.rstrip('/')}/{self.models_path.lstrip('/')}"


@dataclass(frozen=True)
class DiscoveredModel:
    """Provider-neutral metadata for one discovered model identifier."""

    model_name: str
    display_name: str
    capabilities: tuple[str, ...] = ("chat",)
    modalities: tuple[str, ...] = ("text",)
    context_window: int | None = None
    input_price_usd_per_million: float | None = None
    output_price_usd_per_million: float | None = None


@dataclass(frozen=True)
class CatalogModelRecord:
    """A discovered model associated with its provider account."""

    provider_account_id: str
    model: DiscoveredModel


class ProviderCatalogUnavailable(RuntimeError):
    """Raised when a durable catalog cannot produce any usable provider model."""


class CatalogHttpError(RuntimeError):
    """Stable, secret-free provider catalog transport failure."""

    def __init__(self, code: str, *, transient: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


class ProviderCatalogStore(Protocol):
    """Persistence contract shared by in-memory tests and PostgreSQL production."""

    def upsert_account(self, account: ProviderAccount) -> None:
        """Insert or update one provider account without storing a secret value."""
        ...

    def replace_catalog(self, account: ProviderAccount, models: Sequence[DiscoveredModel]) -> None:
        """Atomically replace one successful provider account's current model set."""
        ...

    def record_failure(self, account: ProviderAccount, error_code: str) -> None:
        """Record a failed refresh without changing the last-known-good model set."""
        ...

    def enabled_models(self) -> list[CatalogModelRecord]:
        """Return usable models belonging to enabled provider accounts."""
        ...

    def all_models(self) -> list[CatalogModelRecord]:
        """Return catalog history including models on disabled accounts."""
        ...

    def has_models(self, provider_account_id: str) -> bool:
        """Return whether an account retains any enabled last-known-good model."""
        ...


DEFAULT_PROVIDER_ACCOUNTS: tuple[ProviderAccount, ...] = (
    ProviderAccount(
        provider_account_id="nvidia_nim_primary",
        provider_name="nvidia_nim",
        credential_name="NVIDIA_NIM_API_KEY",
        base_url="https://integrate.api.nvidia.com/v1",
        priority_rank=30,
    ),
    ProviderAccount(
        provider_account_id="nvidia_nim_secondary",
        provider_name="nvidia_nim",
        credential_name="NVIDIA_NIM_API_KEY_SUB",
        base_url="https://integrate.api.nvidia.com/v1",
        priority_rank=25,
    ),
    ProviderAccount(
        provider_account_id="bytez_primary",
        provider_name="bytez",
        credential_name="BYTEZ_API_KEY",
        base_url="https://api.bytez.com",
        models_path="/models/v2",
        transport_name="bytez_v2",
        auth_prefix="Key",
        priority_rank=10,
    ),
    ProviderAccount(
        provider_account_id="openrouter_primary",
        provider_name="openrouter",
        credential_name="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        priority_rank=20,
    ),
    ProviderAccount(
        provider_account_id="openai_primary",
        provider_name="openai",
        credential_name="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        priority_rank=20,
    ),
)
"""Fixed bootstrap inventory corresponding to the five organization secrets."""


class InMemoryProviderCatalogStore:
    """Thread-free deterministic catalog store for tests and standalone evaluation."""

    def __init__(self) -> None:
        self._accounts: dict[str, ProviderAccount] = {}
        self._models: dict[str, dict[str, DiscoveredModel]] = {}
        self.refresh_runs: list[dict[str, Any]] = []

    def upsert_account(self, account: ProviderAccount) -> None:
        """Store an account definition, preserving its model history."""
        self._accounts[account.provider_account_id] = account

    def replace_catalog(self, account: ProviderAccount, models: Sequence[DiscoveredModel]) -> None:
        """Replace one account catalog and append successful refresh evidence."""
        self.upsert_account(account)
        unique = {model.model_name: model for model in models if model.model_name}
        self._models[account.provider_account_id] = unique
        now = _utc_now_text()
        self.refresh_runs.append(
            {
                "catalog_refresh_id": _refresh_id(account.provider_account_id, now),
                "provider_account_id": account.provider_account_id,
                "refresh_status": "refreshed",
                "observed_model_count": len(unique),
                "error_code": None,
                "started_at": now,
                "finished_at": now,
            }
        )

    def record_failure(self, account: ProviderAccount, error_code: str) -> None:
        """Append failure evidence while leaving the prior model mapping unchanged."""
        self.upsert_account(account)
        now = _utc_now_text()
        self.refresh_runs.append(
            {
                "catalog_refresh_id": _refresh_id(account.provider_account_id, now),
                "provider_account_id": account.provider_account_id,
                "refresh_status": "failed",
                "observed_model_count": 0,
                "error_code": error_code,
                "started_at": now,
                "finished_at": now,
            }
        )

    def enabled_models(self) -> list[CatalogModelRecord]:
        """Return sorted model rows whose provider account is enabled."""
        records: list[CatalogModelRecord] = []
        for account_id, models in self._models.items():
            account = self._accounts.get(account_id)
            if account is None or not account.enabled:
                continue
            records.extend(CatalogModelRecord(account_id, model) for model in models.values())
        return sorted(records, key=lambda row: (row.provider_account_id, row.model.model_name))

    def all_models(self) -> list[CatalogModelRecord]:
        """Return every retained model regardless of account enablement."""
        return sorted(
            (
                CatalogModelRecord(account_id, model)
                for account_id, models in self._models.items()
                for model in models.values()
            ),
            key=lambda row: (row.provider_account_id, row.model.model_name),
        )

    def has_models(self, provider_account_id: str) -> bool:
        """Return whether an account has at least one retained model."""
        return bool(self._models.get(provider_account_id))

    def account(self, provider_account_id: str) -> ProviderAccount | None:
        """Return one account definition for deterministic tests and factories."""
        return self._accounts.get(provider_account_id)


class PostgresProviderCatalogStore:
    """Normalized PostgreSQL provider catalog with account-scoped transactions."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ProviderCatalogUnavailable("provider catalog requires a PostgreSQL DSN")
        self._dsn = dsn
        self._schema_ready = False

    def _connect(self):  # pragma: no cover - requires a live production database
        try:
            import psycopg
        except ImportError as exc:
            raise ProviderCatalogUnavailable(
                "provider catalog requires contextual-orchestrator[db]"
            ) from exc
        return psycopg.connect(self._dsn)

    def _ensure_schema(self, connection: Any) -> None:  # pragma: no cover - live database
        if self._schema_ready:
            return
        with connection.cursor() as cursor:
            cursor.execute(PROVIDER_CATALOG_SCHEMA_SQL)
        connection.commit()
        self._schema_ready = True

    def upsert_account(self, account: ProviderAccount) -> None:  # pragma: no cover - live database
        with self._connect() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                _upsert_account_row(cursor, account)
            connection.commit()

    def replace_catalog(
        self, account: ProviderAccount, models: Sequence[DiscoveredModel]
    ) -> None:  # pragma: no cover - live database
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
                finished_at = _utc_now()
                _insert_refresh_row(
                    cursor,
                    account.provider_account_id,
                    "refreshed",
                    len(unique),
                    None,
                    started_at,
                    finished_at,
                )
            connection.commit()

    def record_failure(
        self, account: ProviderAccount, error_code: str
    ) -> None:  # pragma: no cover - live database
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

    def enabled_models(self) -> list[CatalogModelRecord]:  # pragma: no cover - live database
        return self._read_models(enabled_accounts_only=True)

    def all_models(self) -> list[CatalogModelRecord]:  # pragma: no cover - live database
        return self._read_models(enabled_accounts_only=False)

    def has_models(self, provider_account_id: str) -> bool:  # pragma: no cover - live database
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

    def _read_models(
        self, *, enabled_accounts_only: bool
    ) -> list[CatalogModelRecord]:  # pragma: no cover - live database
        condition = "AND a.enabled_flag = true" if enabled_accounts_only else ""
        with self._connect() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT m.provider_account_id, m.provider_model_id, m.model_name, "
                    "m.display_name, m.context_window, m.input_price_usd_per_million, "
                    "m.output_price_usd_per_million "
                    "FROM provider_models m JOIN provider_accounts a "
                    "ON a.provider_account_id = m.provider_account_id "
                    f"WHERE m.enabled_flag = true {condition} "  # nosec B608 - fixed internal fragment
                    "ORDER BY m.provider_account_id, m.model_name"
                )
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


class _PinnedCatalogConnection(http.client.HTTPSConnection):
    """Connect to a validated address while retaining hostname TLS verification."""

    def __init__(
        self,
        hostname: str,
        pinned_ip: str,
        port: int,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(hostname, port=port, timeout=timeout, context=context)
        self._pinned_ip = pinned_ip
        self._catalog_hostname = hostname

    def connect(self) -> None:  # pragma: no cover - real network boundary
        raw_socket = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self._catalog_hostname,
            )
        except Exception:
            raw_socket.close()
            raise


class ProviderCatalogHttpClient:
    """Bounded DNS-pinned HTTPS GET client for provider model listings."""

    TRANSIENT_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        max_attempts: int = 3,
        deadline_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        if timeout_seconds <= 0 or max_attempts < 1 or deadline_seconds <= 0:
            raise ValueError("catalog HTTP limits must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.deadline_seconds = deadline_seconds
        self._sleep = sleep
        self._random_uniform = random_uniform
        self._ssl_context = ssl.create_default_context()

    def discover(self, account: ProviderAccount, credential: str) -> list[DiscoveredModel]:
        """Fetch and normalize one account's model document with bounded retries."""
        if not account.models_url:
            raise CatalogHttpError("catalog_endpoint_not_configured")
        started = time.monotonic()
        last_error = CatalogHttpError("provider_unavailable", transient=True)
        for attempt in range(self.max_attempts):
            if time.monotonic() - started >= self.deadline_seconds:
                raise CatalogHttpError("catalog_deadline_exceeded", transient=True)
            try:
                document = self._request_json(account, credential)
                models = normalize_models_document(document)
                if not models:
                    raise CatalogHttpError("catalog_contains_no_models")
                return models
            except CatalogHttpError as exc:
                last_error = exc
                if not exc.transient or attempt + 1 >= self.max_attempts:
                    raise
                ceiling = min(8.0, 0.5 * (2**attempt))
                self._sleep(self._random_uniform(0.0, ceiling))
        raise last_error

    def _request_json(
        self, account: ProviderAccount, credential: str
    ) -> dict[str, Any]:  # pragma: no cover - real provider boundary
        parsed = urlparse(account.models_url or "")
        if parsed.scheme != "https" or not parsed.hostname:
            raise CatalogHttpError("catalog_url_must_use_https")
        if parsed.username is not None or parsed.password is not None:
            raise CatalogHttpError("catalog_url_must_not_contain_userinfo")
        port = parsed.port or 443
        addresses = _validated_global_addresses(parsed.hostname, port)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        authorization = f"{account.auth_prefix} {credential}".strip()
        headers = {
            account.auth_header_name: authorization,
            "Accept": "application/json",
            "Connection": "close",
            "User-Agent": "contextual-orchestrator-provider-catalog/1",
        }
        last_network_error: BaseException | None = None
        for address in addresses:
            connection = _PinnedCatalogConnection(
                parsed.hostname,
                address,
                port,
                self.timeout_seconds,
                self._ssl_context,
            )
            try:
                connection.request("GET", target, headers=headers)
                response = connection.getresponse()
                status = response.status
                if status >= 300:
                    response.close()
                    connection.close()
                    if status in {401, 403}:
                        raise CatalogHttpError("catalog_authentication_failed")
                    raise CatalogHttpError(
                        f"catalog_http_{status}",
                        transient=status in self.TRANSIENT_STATUS,
                    )
                content_type = (response.getheader("Content-Type") or "").lower()
                if "json" not in content_type:
                    response.close()
                    connection.close()
                    raise CatalogHttpError("catalog_content_type_invalid")
                payload = response.read(CATALOG_RESPONSE_MAX_BYTES + 1)
                response.close()
                connection.close()
                if len(payload) > CATALOG_RESPONSE_MAX_BYTES:
                    raise CatalogHttpError("catalog_response_too_large")
                try:
                    document = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                    raise CatalogHttpError("catalog_json_invalid") from None
                if not isinstance(document, dict):
                    raise CatalogHttpError("catalog_json_must_be_object")
                return document
            except CatalogHttpError:
                raise
            except (OSError, http.client.HTTPException, TimeoutError) as exc:
                connection.close()
                last_network_error = exc
                continue
        raise CatalogHttpError("catalog_network_failure", transient=True) from last_network_error


class ProviderCatalogService:
    """Coordinate isolated provider refreshes and build the runtime agent pool."""

    def __init__(
        self,
        *,
        store: ProviderCatalogStore,
        accounts: Sequence[ProviderAccount] = DEFAULT_PROVIDER_ACCOUNTS,
        discover: Callable[[ProviderAccount, str], Sequence[DiscoveredModel]] | None = None,
    ) -> None:
        self.store = store
        self.accounts = tuple(accounts)
        self._account_by_id = {account.provider_account_id: account for account in self.accounts}
        client = ProviderCatalogHttpClient()
        self._discover = discover or client.discover

    def refresh_all(self) -> dict[str, Any]:
        """Refresh each account independently and preserve stale usable catalogs."""
        provider_rows: dict[str, dict[str, Any]] = {}
        for account in self.accounts:
            self.store.upsert_account(account)
            if not account.enabled:
                provider_rows[account.provider_account_id] = {
                    "status": "disabled",
                    "model_count": 0,
                    "error_code": None,
                }
                continue
            credential = get_credential(account.credential_name)
            if not credential:
                provider_rows[account.provider_account_id] = self._failed_refresh(
                    account,
                    "credential_not_registered",
                )
                continue
            try:
                models = list(self._discover(account, credential))
                if not models:
                    raise CatalogHttpError("catalog_contains_no_models")
                self.store.replace_catalog(account, models)
                provider_rows[account.provider_account_id] = {
                    "status": "refreshed",
                    "model_count": len(models),
                    "error_code": None,
                }
            except CatalogHttpError as exc:
                provider_rows[account.provider_account_id] = self._failed_refresh(
                    account,
                    exc.code,
                )
            except Exception:
                provider_rows[account.provider_account_id] = self._failed_refresh(
                    account,
                    "catalog_adapter_failure",
                )
        candidates = self.store.enabled_models()
        if not candidates:
            raise ProviderCatalogUnavailable(
                "no usable provider model exists after catalog refresh"
            )
        return {
            "provider_accounts": provider_rows,
            "candidate_model_count": len(candidates),
            "measurement_status": "provider_catalog_snapshot",
        }

    def _failed_refresh(self, account: ProviderAccount, code: str) -> dict[str, Any]:
        """Record failure and classify whether last-known-good service remains available."""
        self.store.record_failure(account, code)
        stale_available = self.store.has_models(account.provider_account_id)
        return {
            "status": "stale_available" if stale_available else "failed",
            "model_count": 0,
            "error_code": code,
        }

    def candidate_agents(self) -> list[ModelAgent]:
        """Convert enabled catalog rows into role-tagged, failover-capable agents."""
        agents: list[ModelAgent] = []
        for record in self.store.enabled_models():
            account = self._account_by_id.get(record.provider_account_id)
            if account is None or not account.enabled:
                continue
            model = record.model
            agents.append(
                ModelAgent(
                    id=_agent_id(account.provider_account_id, model.model_name),
                    model=model.model_name,
                    base_url=account.base_url,
                    credential_key=account.credential_name,
                    tags=_agent_tags(model),
                    priority=account.priority_rank + _model_priority(model),
                    provider_name=account.provider_name,
                )
            )
        return agents


def bootstrap_provider_credentials(
    environment: Mapping[str, str],
    *,
    require_all: bool,
    accounts: Sequence[ProviderAccount] = DEFAULT_PROVIDER_ACCOUNTS,
) -> dict[str, list[str]]:
    """Transport the fixed provider-secret inventory into the credential registry.

    Validation happens before mutation when ``require_all`` is true, preventing a
    partially updated production credential set. The returned summary contains
    names only and is therefore safe for CI logs.
    """
    values = {
        account.credential_name: str(environment.get(account.credential_name, "")).strip()
        for account in accounts
    }
    missing = [name for name, value in values.items() if not value]
    if require_all and missing:
        raise ProviderCatalogUnavailable("provider credential inventory is incomplete")
    registered: list[str] = []
    for account in accounts:
        value = values[account.credential_name]
        if not value:
            continue
        register_credential(account.credential_name, value)
        registered.append(account.credential_name)
    return {
        "registered_credentials": registered,
        "missing_credentials": missing,
    }


def normalize_models_document(document: Mapping[str, Any]) -> list[DiscoveredModel]:
    """Normalize common OpenAI/OpenRouter/Bytez listing shapes into model rows."""
    raw_rows: Any = document.get("data")
    if not isinstance(raw_rows, list):
        raw_rows = document.get("models")
    if isinstance(raw_rows, dict):
        raw_rows = list(raw_rows.values())
    if not isinstance(raw_rows, list):
        return []
    models: dict[str, DiscoveredModel] = {}
    for raw in raw_rows:
        if isinstance(raw, str):
            raw = {"id": raw}
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("id") or raw.get("model") or raw.get("name") or "").strip()
        if not name or len(name) > 512:
            continue
        display_name = str(raw.get("name") or raw.get("display_name") or name).strip()[:512] or name
        architecture = raw.get("architecture") if isinstance(raw.get("architecture"), Mapping) else {}
        input_modalities = _string_values(
            architecture.get("input_modalities") or raw.get("input_modalities") or raw.get("modalities")
        )
        output_modalities = _string_values(
            architecture.get("output_modalities") or raw.get("output_modalities")
        )
        modalities = tuple(sorted(set(input_modalities + output_modalities) or {"text"}))
        capabilities = _infer_capabilities(name, raw, modalities)
        context_window = _optional_positive_int(
            raw.get("context_length") or raw.get("context_window") or raw.get("max_context_length")
        )
        pricing = raw.get("pricing") if isinstance(raw.get("pricing"), Mapping) else {}
        input_price = _per_token_price_to_million(
            pricing.get("prompt") or raw.get("input_price_per_token")
        )
        output_price = _per_token_price_to_million(
            pricing.get("completion") or raw.get("output_price_per_token")
        )
        models[name] = DiscoveredModel(
            model_name=name,
            display_name=display_name,
            capabilities=capabilities,
            modalities=modalities,
            context_window=context_window,
            input_price_usd_per_million=input_price,
            output_price_usd_per_million=output_price,
        )
    return [models[name] for name in sorted(models)]


def build_catalog_orchestrator(
    store: ProviderCatalogStore,
    *,
    accounts: Sequence[ProviderAccount] = DEFAULT_PROVIDER_ACCOUNTS,
    client: ModelClient | None = None,
    **orchestrator_options: Any,
) -> TaskOrchestrator:
    """Build a normal :class:`TaskOrchestrator` from the durable candidate pool."""
    service = ProviderCatalogService(store=store, accounts=accounts)
    agents = service.candidate_agents()
    if not agents:
        raise ProviderCatalogUnavailable("provider catalog contains no enabled agents")
    return TaskOrchestrator(agents, client=client, **orchestrator_options)


def _upsert_account_row(cursor: Any, account: ProviderAccount) -> None:
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


def _insert_refresh_row(
    cursor: Any,
    account_id: str,
    status: str,
    count: int,
    error_code: str | None,
    started_at: datetime,
    finished_at: datetime,
) -> None:
    """Insert one immutable provider refresh evidence row."""
    refresh_id = _refresh_id(account_id, finished_at.isoformat())
    cursor.execute(
        "INSERT INTO catalog_refresh_runs ("
        "catalog_refresh_id, provider_account_id, refresh_status, observed_model_count, "
        "error_code, started_at, finished_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (refresh_id, account_id, status, count, error_code, started_at, finished_at),
    )


def _validated_global_addresses(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve and accept only globally routable addresses for credentialed egress."""
    addresses: list[str] = []
    try:
        candidates = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise CatalogHttpError("catalog_dns_failure", transient=True) from None
    for candidate in candidates:
        address = ipaddress.ip_address(candidate[4][0])
        if (
            not address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
        ):
            raise CatalogHttpError("catalog_destination_not_public")
        value = str(address)
        if value not in addresses:
            addresses.append(value)
    if not addresses:
        raise CatalogHttpError("catalog_dns_empty", transient=True)
    return tuple(addresses)


def _infer_capabilities(
    model_name: str,
    raw: Mapping[str, Any],
    modalities: Sequence[str],
) -> tuple[str, ...]:
    """Infer conservative routing tags from provider metadata and model naming."""
    lowered = model_name.lower()
    declared = set(_string_values(raw.get("capabilities")))
    capabilities = {value.lower() for value in declared}
    if not any(token in lowered for token in ("embed", "rerank", "moderation")):
        capabilities.add("chat")
    if any(token in lowered for token in ("reason", "o1", "o3", "r1", "thinking")):
        capabilities.add("reasoning")
    if any(token in lowered for token in ("code", "coder", "codestral", "devstral")):
        capabilities.add("coding")
    if any(token in lowered for token in ("embed", "embedding")):
        capabilities.add("embeddings")
    if "image" in modalities or "vision" in lowered or "vl" in lowered:
        capabilities.add("vision")
    if "audio" in modalities or any(token in lowered for token in ("audio", "whisper", "speech")):
        capabilities.add("audio")
    if any(token in lowered for token in ("moderation", "guard")):
        capabilities.add("moderation")
    return tuple(sorted(capabilities or {"chat"}))


def _agent_tags(model: DiscoveredModel) -> tuple[str, ...]:
    """Map provider capabilities into the orchestrator's role/domain tag vocabulary."""
    tags: set[str] = set(model.capabilities)
    if "chat" in tags:
        tags.update(("writing", "summarization", "classification"))
    if "reasoning" in tags:
        tags.update(("planning", "research", "verification"))
    if "coding" in tags:
        tags.update(("implementation", "debugging"))
    if "vision" in tags:
        tags.update(("image", "multimodal"))
    if "audio" in tags:
        tags.update(("speech", "multimodal"))
    return tuple(sorted(tags))


def _model_priority(model: DiscoveredModel) -> int:
    """Score capability and context first, using known price only as a small tie-break."""
    score = 0
    score += 20 if "reasoning" in model.capabilities else 0
    score += 15 if "coding" in model.capabilities else 0
    score += 8 if "vision" in model.capabilities else 0
    if model.context_window:
        score += min(10, model.context_window // 100_000)
    known_prices = [
        value
        for value in (
            model.input_price_usd_per_million,
            model.output_price_usd_per_million,
        )
        if value is not None
    ]
    if known_prices:
        average = sum(known_prices) / len(known_prices)
        score += max(0, 5 - min(5, int(average)))
    return score


def _agent_id(provider_account_id: str, model_name: str) -> str:
    """Create a bounded two-or-more-word snake-case agent identifier."""
    slug = re.sub(r"[^a-z0-9]+", "_", model_name.lower()).strip("_")
    if not slug:
        slug = "model_worker"
    digest = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:8]
    identifier = f"{provider_account_id}_{slug}_{digest}"
    return identifier[:120].rstrip("_")


def _provider_model_id(provider_account_id: str, model_name: str) -> str:
    """Return a stable non-secret identifier for one account/model pair."""
    material = f"{provider_account_id}\0{model_name}".encode("utf-8")
    return f"provider_model_{hashlib.sha256(material).hexdigest()}"


def _refresh_id(account_id: str, timestamp: str) -> str:
    """Return an immutable refresh identifier without exposing credentials."""
    material = f"{account_id}\0{timestamp}".encode("utf-8")
    return f"catalog_refresh_{hashlib.sha256(material).hexdigest()}"


def _string_values(value: Any) -> list[str]:
    """Return bounded, non-empty strings from scalar or sequence metadata."""
    if isinstance(value, str):
        values: Iterable[Any] = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = value
    else:
        return []
    result: list[str] = []
    for item in values:
        if isinstance(item, str):
            normalized = item.strip().lower()
            if normalized and len(normalized) <= 128:
                result.append(normalized)
    return result


def _optional_positive_int(value: Any) -> int | None:
    """Return a positive integer metadata value, rejecting booleans and overflow."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed <= 0 or parsed > 10_000_000_000:
        return None
    return parsed


def _per_token_price_to_million(value: Any) -> float | None:
    """Convert a finite non-negative per-token USD price to per-million units."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed * 1_000_000


def _optional_float(value: Any) -> float | None:
    """Convert a finite database numeric value to float, preserving null."""
    if value is None:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _utc_now_text() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return _utc_now().isoformat()


def _safe_cli_summary(credential_summary: Mapping[str, Any], catalog_summary: Mapping[str, Any]) -> dict[str, Any]:
    """Build a log-safe bootstrap summary containing no credential values."""
    return {
        "registered_credentials": list(credential_summary.get("registered_credentials", [])),
        "missing_credentials": list(credential_summary.get("missing_credentials", [])),
        "candidate_model_count": int(catalog_summary.get("candidate_model_count", 0)),
        "provider_accounts": dict(catalog_summary.get("provider_accounts", {})),
        "measurement_status": "provider_catalog_bootstrap",
    }


def _write_agents_file(path: str, agents: Sequence[ModelAgent]) -> None:
    """Atomically write a secret-free agent configuration JSON document."""
    target = os.path.abspath(path)
    parent = os.path.dirname(target) or "."
    os.makedirs(parent, exist_ok=True)
    temporary = f"{target}.tmp-{os.getpid()}"
    payload = {"agents": [agent.to_config() for agent in agents]}
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: Sequence[str] | None = None) -> int:
    """Bootstrap credentials, refresh the durable catalog, and optionally export agents."""
    parser = argparse.ArgumentParser(description="Bootstrap and refresh the durable provider catalog.")
    parser.add_argument("command", choices=("bootstrap-and-sync", "sync", "export-agents"))
    parser.add_argument(
        "--catalog-dsn",
        default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_CATALOG_DSN")
        or os.environ.get("CONTEXTUAL_ORCHESTRATOR_KV_DSN", ""),
        help="PostgreSQL DSN used for provider metadata (bootstrap transport only).",
    )
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--agents-output", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    store = PostgresProviderCatalogStore(args.catalog_dsn)
    credential_summary: dict[str, list[str]] = {
        "registered_credentials": [],
        "missing_credentials": [],
    }
    if args.command == "bootstrap-and-sync":
        credential_summary = bootstrap_provider_credentials(
            os.environ,
            require_all=args.require_all,
        )
    service = ProviderCatalogService(store=store)
    if args.command in {"bootstrap-and-sync", "sync"}:
        catalog_summary = service.refresh_all()
    else:
        catalog_summary = {
            "candidate_model_count": len(store.enabled_models()),
            "provider_accounts": {},
        }
    agents = service.candidate_agents()
    if not agents:
        raise ProviderCatalogUnavailable("provider catalog contains no enabled agents")
    if args.agents_output:
        _write_agents_file(args.agents_output, agents)
    print(json.dumps(_safe_cli_summary(credential_summary, catalog_summary), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through CLI integration
    try:
        raise SystemExit(main())
    except ProviderCatalogUnavailable as exc:
        print(json.dumps({"error": "provider_catalog_unavailable", "message": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from None
