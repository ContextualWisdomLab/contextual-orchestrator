"""Normalized durable provider-model catalog persistence.

This module owns provider-account/model metadata persistence and last-known-good
refresh behavior. It never performs network I/O and never stores credential
values. Discovery transport remains in ``model_discovery``; runtime selection
remains in the ordinary orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import math
import re
import threading
import uuid
from typing import Callable, Mapping, Protocol, Sequence

from .model_discovery import DiscoveredModel, ProviderModelSource


PROVIDER_CATALOG_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS provider_account (
    provider_account_id text PRIMARY KEY,
    provider_name text NOT NULL,
    credential_name text NOT NULL,
    list_url text NOT NULL,
    chat_base_url text NOT NULL,
    auth_scheme text NOT NULL,
    discovery_style text NOT NULL,
    task_filter text NOT NULL,
    enabled_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider_name, credential_name)
);

CREATE TABLE IF NOT EXISTS provider_model (
    provider_model_id text PRIMARY KEY,
    provider_account_id text NOT NULL
        REFERENCES provider_account(provider_account_id) ON DELETE CASCADE,
    model_name text NOT NULL,
    prompt_price_per_1k numeric(20, 8),
    completion_price_per_1k numeric(20, 8),
    currency_code text NOT NULL,
    serving_eligible_flag boolean NOT NULL DEFAULT false,
    enabled_flag boolean NOT NULL DEFAULT true,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    UNIQUE (provider_account_id, model_name)
);

CREATE TABLE IF NOT EXISTS model_serving_tag (
    provider_model_id text NOT NULL
        REFERENCES provider_model(provider_model_id) ON DELETE CASCADE,
    tag_name text NOT NULL,
    PRIMARY KEY (provider_model_id, tag_name)
);

CREATE TABLE IF NOT EXISTS model_policy_source (
    provider_model_id text NOT NULL
        REFERENCES provider_model(provider_model_id) ON DELETE CASCADE,
    policy_source_url text NOT NULL,
    PRIMARY KEY (provider_model_id, policy_source_url)
);

CREATE TABLE IF NOT EXISTS catalog_refresh_run (
    catalog_refresh_run_id text PRIMARY KEY,
    provider_account_id text NOT NULL
        REFERENCES provider_account(provider_account_id) ON DELETE CASCADE,
    refresh_status text NOT NULL,
    observed_model_count integer NOT NULL DEFAULT 0,
    eligible_model_count integer NOT NULL DEFAULT 0,
    error_code text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS provider_model_account_idx
    ON provider_model (provider_account_id, enabled_flag, serving_eligible_flag);
CREATE INDEX IF NOT EXISTS catalog_refresh_account_idx
    ON catalog_refresh_run (provider_account_id, finished_at DESC);
"""
"""Third-normal-form schema for provider accounts, models, tags, and refreshes."""


class ProviderCatalogError(RuntimeError):
    """Raised when durable provider catalog metadata cannot be persisted or read."""


@dataclass(frozen=True)
class CatalogRefreshEvidence:
    """Secret-free evidence for one provider-account catalog refresh."""

    provider_account_id: str
    refresh_status: str
    observed_model_count: int
    eligible_model_count: int
    error_code: str | None
    started_at: datetime
    finished_at: datetime


class ProviderCatalogStore(Protocol):
    """Persistence boundary for provider model metadata and last-known-good rows."""

    @property
    def backend_name(self) -> str:
        """Return a stable backend name for secret-free operator evidence."""
        ...

    def record_success(
        self,
        source: ProviderModelSource,
        models: Sequence[DiscoveredModel],
        *,
        eligible_model_ids: set[str],
        serving_tags: Mapping[str, tuple[str, ...]],
    ) -> None:
        """Replace one provider account's current catalog atomically."""
        ...

    def record_failure(
        self,
        source: ProviderModelSource,
        *,
        error_code: str,
    ) -> None:
        """Record failure without changing last-known-good enabled models."""
        ...

    def serving_models(
        self,
        source: ProviderModelSource,
    ) -> list[DiscoveredModel]:
        """Return enabled, serving-eligible last-known-good models."""
        ...

    def refresh_evidence(self) -> tuple[CatalogRefreshEvidence, ...]:
        """Return refresh evidence in insertion order."""
        ...


_SLUG_RE = re.compile(r"[^a-z0-9]+")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_ALLOWED_REFRESH_ERROR_CODES = frozenset(
    {"provider_discovery_error", "empty_provider_catalog", "unknown_error"}
)


def provider_account_id(source: ProviderModelSource) -> str:
    """Return a stable two-or-more-word snake-case provider account ID."""
    provider = _SLUG_RE.sub("_", source.provider_name.casefold()).strip("_")
    credential = _SLUG_RE.sub("_", source.credential_name.casefold()).strip("_")
    if not provider or not credential:
        raise ProviderCatalogError("provider account identity is incomplete")
    return f"{provider}_{credential}"


def provider_model_id(source: ProviderModelSource, model_name: str) -> str:
    """Return a stable opaque ID for one account-scoped model name."""
    normalized = model_name.strip()
    if not normalized:
        raise ProviderCatalogError("provider model name is empty")
    digest = hashlib.sha256(
        f"{provider_account_id(source)}\0{normalized}".encode("utf-8")
    ).hexdigest()
    return f"provider_model_{digest[:32]}"


def _now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _normalize_price(value: object) -> float | None:
    """Return one finite non-negative price, or ``None`` when unknown, underflowed, or overflowed.

    Parses through ``Decimal`` first so a nonzero price that underflows to
    ``0.0`` in float (e.g. a stray ``1e-10000``) is rejected as unknown
    rather than silently accepted as a legitimate free price. A ``Decimal``
    can still be finite while its ``float()`` conversion overflows to
    ``inf`` (e.g. ``1e10000``), so ``math.isfinite`` is checked separately
    on the converted value.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal_value = Decimal(str(value))
        number = float(decimal_value)
    except (ArithmeticError, TypeError, ValueError):
        return None
    if (
        not decimal_value.is_finite()
        or not math.isfinite(number)
        or decimal_value < 0
        or (decimal_value != 0 and number == 0)
    ):
        return None
    return number


_UNKNOWN_CURRENCY = "UNKNOWN"


def _normalize_currency(value: object) -> str:
    """Return an ISO-style three-letter currency code, or an explicit unknown marker.

    An unrecognized currency must never collapse to ``USD`` by default: doing
    so would let a priced model with an unverified currency rank as a
    comparable USD cost. ``_UNKNOWN_CURRENCY`` deliberately fails
    ``_currency_is_comparable`` against every real default currency.
    """
    if not isinstance(value, str):
        return _UNKNOWN_CURRENCY
    normalized = value.strip().upper()
    return normalized if _CURRENCY_RE.fullmatch(normalized) else _UNKNOWN_CURRENCY


def _normalize_error_code(value: object) -> str:
    """Return one approved secret-free provider refresh failure code."""
    if not isinstance(value, str):
        return "unknown_error"
    normalized = value.strip().casefold()
    return normalized if normalized in _ALLOWED_REFRESH_ERROR_CODES else "unknown_error"


def _normalize_tags(tags: Sequence[str]) -> tuple[str, ...]:
    """Return deterministic, valid, duplicate-free serving tags."""
    normalized: list[str] = []
    for raw in tags:
        if not isinstance(raw, str):
            continue
        tag = raw.strip().casefold()
        if not tag or not re.fullmatch(r"[a-z][a-z0-9_]*(?::[a-z0-9_]+)?", tag):
            continue
        if tag not in normalized:
            normalized.append(tag)
    return tuple(normalized)


def normalize_discovered_model(
    source: ProviderModelSource,
    model: DiscoveredModel,
) -> DiscoveredModel:
    """Normalize one discovered row and enforce its provider-account identity."""
    name = model.model_id.strip() if isinstance(model.model_id, str) else ""
    if not name:
        raise ProviderCatalogError("provider model name is empty")
    if (
        model.provider_name != source.provider_name
        or model.credential_name != source.credential_name
    ):
        raise ProviderCatalogError("provider model belongs to a different account")
    return DiscoveredModel(
        provider_name=source.provider_name,
        model_id=name,
        credential_name=source.credential_name,
        chat_base_url=source.chat_base_url,
        auth_scheme=source.auth_scheme,
        prompt_price_per_1k=_normalize_price(model.prompt_price_per_1k),
        completion_price_per_1k=_normalize_price(
            model.completion_price_per_1k
        ),
        currency_code=_normalize_currency(model.currency_code),
        capabilities=tuple(model.capabilities),
        input_modalities=tuple(model.input_modalities),
        output_modalities=tuple(model.output_modalities),
        is_free=bool(model.is_free),
        supports_zero_data_retention=model.supports_zero_data_retention,
        supports_no_training=model.supports_no_training,
        supports_no_prompt_retention=model.supports_no_prompt_retention,
        privacy_policy_urls=tuple(model.privacy_policy_urls),
    )


def _restore_model_semantics(
    model: DiscoveredModel, tags: Sequence[str]
) -> DiscoveredModel:
    """Restore normalized discovery semantics from persisted serving tags."""
    normalized = _normalize_tags(tags)
    return DiscoveredModel(
        provider_name=model.provider_name,
        model_id=model.model_id,
        credential_name=model.credential_name,
        chat_base_url=model.chat_base_url,
        auth_scheme=model.auth_scheme,
        capabilities=tuple(
            tag.removeprefix("capability:")
            for tag in normalized
            if tag.startswith("capability:")
        ),
        input_modalities=tuple(tag.removeprefix("input:") for tag in normalized if tag.startswith("input:")),
        output_modalities=tuple(tag.removeprefix("output:") for tag in normalized if tag.startswith("output:")),
        prompt_price_per_1k=model.prompt_price_per_1k,
        completion_price_per_1k=model.completion_price_per_1k,
        currency_code=model.currency_code,
        is_free="cost:free" in normalized,
        supports_zero_data_retention=(
            True if "privacy:zdr" in normalized else False if "privacy:no_zdr" in normalized else None
        ),
        supports_no_training=(
            True if "privacy:no_training" in normalized else False if "privacy:training_only" in normalized else None
        ),
        supports_no_prompt_retention=(
            True if "privacy:no_retention" in normalized else False if "privacy:retention_only" in normalized else None
        ),
        privacy_policy_urls=tuple(model.privacy_policy_urls),
    )


def _deduplicate_models(
    source: ProviderModelSource,
    models: Sequence[DiscoveredModel],
) -> dict[str, DiscoveredModel]:
    """Normalize and deterministically deduplicate account-scoped models."""
    result: dict[str, DiscoveredModel] = {}
    for model in models:
        normalized = normalize_discovered_model(source, model)
        result[normalized.model_id] = normalized
    return result


class InMemoryProviderCatalogStore:
    """Thread-safe deterministic provider catalog for tests and standalone use."""

    def __init__(self) -> None:
        self._accounts: dict[str, ProviderModelSource] = {}
        self._models: dict[str, dict[str, DiscoveredModel]] = {}
        self._eligible: dict[str, set[str]] = {}
        self._tags: dict[tuple[str, str], tuple[str, ...]] = {}
        self._refreshes: list[CatalogRefreshEvidence] = []
        self._lock = threading.RLock()

    @property
    def backend_name(self) -> str:
        """Return the stable in-memory backend name."""
        return "memory"

    def record_success(
        self,
        source: ProviderModelSource,
        models: Sequence[DiscoveredModel],
        *,
        eligible_model_ids: set[str],
        serving_tags: Mapping[str, tuple[str, ...]],
    ) -> None:
        """Replace one in-memory account catalog."""
        normalized = _deduplicate_models(source, models)
        if not normalized:
            raise ProviderCatalogError("successful provider refresh cannot be empty")
        account_id = provider_account_id(source)
        started_at = _now()
        eligible = set(normalized).intersection(eligible_model_ids)
        with self._lock:
            self._accounts[account_id] = source
            self._models[account_id] = normalized
            self._eligible[account_id] = eligible
            for key in [key for key in self._tags if key[0] == account_id]:
                del self._tags[key]
            for model_name in eligible:
                self._tags[(account_id, model_name)] = _normalize_tags(
                    serving_tags.get(model_name, ())
                )
            self._refreshes.append(
                CatalogRefreshEvidence(
                    account_id,
                    "succeeded",
                    len(normalized),
                    len(eligible),
                    None,
                    started_at,
                    _now(),
                )
            )

    def record_failure(
        self,
        source: ProviderModelSource,
        *,
        error_code: str,
    ) -> None:
        """Record a stable failure without mutating last-known-good models."""
        account_id = provider_account_id(source)
        started_at = _now()
        stable_code = _normalize_error_code(error_code)
        with self._lock:
            self._accounts[account_id] = source
            self._refreshes.append(
                CatalogRefreshEvidence(
                    account_id,
                    "failed",
                    0,
                    0,
                    stable_code,
                    started_at,
                    _now(),
                )
            )

    def serving_models(
        self,
        source: ProviderModelSource,
    ) -> list[DiscoveredModel]:
        """Return deterministic serving models for one account."""
        account_id = provider_account_id(source)
        with self._lock:
            models = self._models.get(account_id, {})
            eligible = self._eligible.get(account_id, set())
            return [
                _restore_model_semantics(
                    models[name], self._tags.get((account_id, name), ())
                )
                for name in sorted(eligible)
                if name in models
            ]

    def serving_tags(
        self,
        source: ProviderModelSource,
        model_name: str,
    ) -> tuple[str, ...]:
        """Return persisted generic serving tags for one model."""
        with self._lock:
            return self._tags.get((provider_account_id(source), model_name), ())

    def refresh_evidence(self) -> tuple[CatalogRefreshEvidence, ...]:
        """Return immutable refresh evidence in insertion order."""
        with self._lock:
            return tuple(self._refreshes)


class PostgresProviderCatalogStore:
    """PostgreSQL provider catalog sharing the credential registry database."""

    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: Callable[[], object] | None = None,
    ) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ProviderCatalogError("provider catalog requires a PostgreSQL DSN")
        self._dsn = dsn
        self._connection_factory = connection_factory
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self._evidence: list[CatalogRefreshEvidence] = []

    @property
    def backend_name(self) -> str:
        """Return the stable PostgreSQL backend name."""
        return "postgres"

    def _connect(self):
        """Open one catalog connection through the injected or psycopg factory."""
        if self._connection_factory is not None:
            return self._connection_factory()
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - packaging boundary
            raise ProviderCatalogError(
                "provider catalog requires contextual-orchestrator[db]"
            ) from exc
        return psycopg.connect(self._dsn)  # pragma: no cover - live database

    def _ensure_schema(self, connection: object) -> None:
        """Create normalized catalog objects once per store instance."""
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with connection.cursor() as cursor:
                cursor.execute(PROVIDER_CATALOG_SCHEMA_SQL)
            connection.commit()
            self._schema_ready = True

    @staticmethod
    def _upsert_account(cursor: object, source: ProviderModelSource) -> str:
        """Upsert one provider account without credential values."""
        account_id = provider_account_id(source)
        cursor.execute(
            "INSERT INTO provider_account ("
            "provider_account_id, provider_name, credential_name, list_url, "
            "chat_base_url, auth_scheme, discovery_style, task_filter, "
            "enabled_flag, created_at, updated_at"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, now(), now()) "
            "ON CONFLICT (provider_account_id) DO UPDATE SET "
            "provider_name = EXCLUDED.provider_name, "
            "credential_name = EXCLUDED.credential_name, "
            "list_url = EXCLUDED.list_url, "
            "chat_base_url = EXCLUDED.chat_base_url, "
            "auth_scheme = EXCLUDED.auth_scheme, "
            "discovery_style = EXCLUDED.discovery_style, "
            "task_filter = EXCLUDED.task_filter, "
            "enabled_flag = true, updated_at = now()",
            (
                account_id,
                source.provider_name,
                source.credential_name,
                source.list_url,
                source.chat_base_url,
                source.auth_scheme,
                source.style,
                source.task_filter,
            ),
        )
        return account_id

    def record_success(
        self,
        source: ProviderModelSource,
        models: Sequence[DiscoveredModel],
        *,
        eligible_model_ids: set[str],
        serving_tags: Mapping[str, tuple[str, ...]],
    ) -> None:
        """Replace one PostgreSQL account catalog in a single transaction."""
        normalized = _deduplicate_models(source, models)
        if not normalized:
            raise ProviderCatalogError("successful provider refresh cannot be empty")
        started_at = _now()
        eligible = set(normalized).intersection(eligible_model_ids)
        with self._connect() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                account_id = self._upsert_account(cursor, source)
                cursor.execute(
                    "UPDATE provider_model SET enabled_flag = false "
                    "WHERE provider_account_id = %s",
                    (account_id,),
                )
                cursor.execute(
                    "DELETE FROM model_serving_tag WHERE provider_model_id IN ("
                    "SELECT provider_model_id FROM provider_model "
                    "WHERE provider_account_id = %s)",
                    (account_id,),
                )
                cursor.execute(
                    "DELETE FROM model_policy_source WHERE provider_model_id IN ("
                    "SELECT provider_model_id FROM provider_model "
                    "WHERE provider_account_id = %s)",
                    (account_id,),
                )
                for model_name, model in normalized.items():
                    model_row_id = provider_model_id(source, model_name)
                    cursor.execute(
                        "INSERT INTO provider_model ("
                        "provider_model_id, provider_account_id, model_name, "
                        "prompt_price_per_1k, completion_price_per_1k, currency_code, "
                        "serving_eligible_flag, enabled_flag, first_seen_at, "
                        "last_seen_at"
                        ") VALUES (%s, %s, %s, %s, %s, %s, %s, "
                        "true, %s, %s) "
                        "ON CONFLICT (provider_model_id) DO UPDATE SET "
                        "model_name = EXCLUDED.model_name, "
                        "prompt_price_per_1k = EXCLUDED.prompt_price_per_1k, "
                        "completion_price_per_1k = EXCLUDED.completion_price_per_1k, "
                        "currency_code = EXCLUDED.currency_code, "
                        "serving_eligible_flag = EXCLUDED.serving_eligible_flag, "
                        "enabled_flag = true, last_seen_at = EXCLUDED.last_seen_at",
                        (
                            model_row_id,
                            account_id,
                            model_name,
                            model.prompt_price_per_1k,
                            model.completion_price_per_1k,
                            model.currency_code,
                            model_name in eligible,
                            started_at,
                            started_at,
                        ),
                    )
                    if model_name in eligible:
                        for tag in _normalize_tags(serving_tags.get(model_name, ())):
                            cursor.execute(
                                "INSERT INTO model_serving_tag "
                                "(provider_model_id, tag_name) "
                                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                                (model_row_id, tag),
                            )
                    for policy_source_url in dict.fromkeys(model.privacy_policy_urls):
                        cursor.execute(
                            "INSERT INTO model_policy_source "
                            "(provider_model_id, policy_source_url) "
                            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                            (model_row_id, policy_source_url),
                        )
                finished_at = _now()
                cursor.execute(
                    "INSERT INTO catalog_refresh_run ("
                    "catalog_refresh_run_id, provider_account_id, refresh_status, "
                    "observed_model_count, eligible_model_count, error_code, "
                    "started_at, finished_at"
                    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        f"catalog_refresh_{uuid.uuid4().hex}",
                        account_id,
                        "succeeded",
                        len(normalized),
                        len(eligible),
                        None,
                        started_at,
                        finished_at,
                    ),
                )
            connection.commit()
        self._evidence.append(
            CatalogRefreshEvidence(
                provider_account_id(source),
                "succeeded",
                len(normalized),
                len(eligible),
                None,
                started_at,
                finished_at,
            )
        )

    def record_failure(
        self,
        source: ProviderModelSource,
        *,
        error_code: str,
    ) -> None:
        """Record a PostgreSQL failure without disabling prior models."""
        started_at = _now()
        stable_code = _normalize_error_code(error_code)
        with self._connect() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                account_id = self._upsert_account(cursor, source)
                finished_at = _now()
                cursor.execute(
                    "INSERT INTO catalog_refresh_run ("
                    "catalog_refresh_run_id, provider_account_id, refresh_status, "
                    "observed_model_count, eligible_model_count, error_code, "
                    "started_at, finished_at"
                    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        f"catalog_refresh_{uuid.uuid4().hex}",
                        account_id,
                        "failed",
                        0,
                        0,
                        stable_code,
                        started_at,
                        finished_at,
                    ),
                )
            connection.commit()
        self._evidence.append(
            CatalogRefreshEvidence(
                provider_account_id(source),
                "failed",
                0,
                0,
                stable_code,
                started_at,
                finished_at,
            )
        )

    def serving_models(
        self,
        source: ProviderModelSource,
    ) -> list[DiscoveredModel]:
        """Read enabled last-known-good serving models for one account."""
        account_id = provider_account_id(source)
        with self._connect() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pm.model_name, pa.chat_base_url, pa.auth_scheme, "
                    "pm.prompt_price_per_1k, pm.completion_price_per_1k, "
                    "pm.currency_code FROM provider_model AS pm "
                    "JOIN provider_account AS pa ON pa.provider_account_id = pm.provider_account_id "
                    "WHERE pm.provider_account_id = %s "
                    "AND pm.enabled_flag = true AND pm.serving_eligible_flag = true "
                    "ORDER BY pm.model_name",
                    (account_id,),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT pm.model_name, mst.tag_name FROM model_serving_tag AS mst "
                    "JOIN provider_model AS pm ON pm.provider_model_id = mst.provider_model_id "
                    "WHERE pm.provider_account_id = %s ORDER BY pm.model_name, mst.tag_name",
                    (account_id,),
                )
                tag_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT pm.model_name, mps.policy_source_url "
                    "FROM model_policy_source AS mps "
                    "JOIN provider_model AS pm ON pm.provider_model_id = mps.provider_model_id "
                    "WHERE pm.provider_account_id = %s "
                    "ORDER BY pm.model_name, mps.policy_source_url",
                    (account_id,),
                )
                policy_source_rows = cursor.fetchall()
        tags_by_model: dict[str, list[str]] = {}
        for model_name, tag_name in tag_rows:
            tags_by_model.setdefault(model_name, []).append(tag_name)
        policy_sources_by_model: dict[str, list[str]] = {}
        for model_name, policy_source_url in policy_source_rows:
            policy_sources_by_model.setdefault(model_name, []).append(
                policy_source_url
            )
        return [
            _restore_model_semantics(DiscoveredModel(
                provider_name=source.provider_name,
                model_id=row[0],
                credential_name=source.credential_name,
                chat_base_url=row[1],
                auth_scheme=row[2],
                prompt_price_per_1k=_normalize_price(row[3]),
                completion_price_per_1k=_normalize_price(row[4]),
                currency_code=_normalize_currency(row[5]),
                privacy_policy_urls=tuple(policy_sources_by_model.get(row[0], ())),
            ), tags_by_model.get(row[0], ()))
            for row in rows
        ]

    def refresh_evidence(self) -> tuple[CatalogRefreshEvidence, ...]:
        """Return evidence emitted by this store instance."""
        return tuple(self._evidence)
