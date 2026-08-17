"""Provider catalog inventory, fail-closed refresh, and agent-pool overlay.

Reuses the PR #574 account inventory and refresh contracts on main without the
PR #96 DNS-pinned egress stack. Runtime secrets resolve through
:func:`get_credential` only. Catalog HTTP reuses
:meth:`ModelClient._validate_provider` (https, host allowlist, private-address
block). Bytez listings use native ``https://api.bytez.com/models/v2`` with
``Authorization: Key`` — not OpenAI ``GET /v1/models``.

Refresh is fail-closed: a failed account keeps last-known-good models and never
invents replacements. Quality/Pareto selection is issue #86 and is not started
here; pool members are ranked by existing capability tags, then known cost.
A served-free channel with a documented list/original price is compared at
that list price rather than ranked as cost ``0.0``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import random
import re
import socket
import time
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence
from urllib.parse import quote
import urllib.error
import urllib.request

from .credentials import get_credential, register_credential
from .orchestrator import ModelAgent, ModelClient, TaskOrchestrator, known_price_rank


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
    channel_input_usd_per_million numeric(20, 8),
    channel_output_usd_per_million numeric(20, 8),
    list_input_usd_per_million numeric(20, 8),
    list_output_usd_per_million numeric(20, 8),
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
"""
"""Normalized catalog schema: credential *names* only, never secret values."""


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
        if self.models_path is None:
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
    channel_input_usd_per_million: float | None = None
    channel_output_usd_per_million: float | None = None
    list_input_usd_per_million: float | None = None
    list_output_usd_per_million: float | None = None


@dataclass(frozen=True)
class CatalogModelRecord:
    """A discovered model associated with its provider account."""

    provider_account_id: str
    model: DiscoveredModel


class ProviderCatalogUnavailable(RuntimeError):
    """Raised when a catalog cannot produce any usable provider model."""


class CatalogHttpError(RuntimeError):
    """Stable, secret-free provider catalog transport failure."""

    def __init__(self, code: str, *, transient: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


class ProviderCatalogStore(Protocol):
    """Persistence contract shared by the in-memory test store and later durable adapters."""

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
        priority_rank=1,
    ),
    ProviderAccount(
        provider_account_id="nvidia_nim_secondary",
        provider_name="nvidia_nim",
        credential_name="NVIDIA_NIM_API_KEY_SUB",
        base_url="https://integrate.api.nvidia.com/v1",
        priority_rank=0,
    ),
    ProviderAccount(
        provider_account_id="bytez_primary",
        provider_name="bytez",
        credential_name="BYTEZ_API_KEY",
        base_url="https://api.bytez.com",
        models_path="/models/v2",
        transport_name="bytez_v2",
        auth_prefix="Key",
        priority_rank=0,
    ),
    ProviderAccount(
        provider_account_id="openrouter_primary",
        provider_name="openrouter",
        credential_name="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        priority_rank=1,
    ),
    ProviderAccount(
        provider_account_id="openai_primary",
        provider_name="openai",
        credential_name="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        priority_rank=1,
    ),
)
"""Fixed bootstrap inventory corresponding to the five organization secrets."""


class InMemoryProviderCatalogStore:
    """Deterministic catalog store for tests and standalone evaluation."""

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
            if not self._accounts[account_id].enabled:
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


class ProviderCatalogHttpClient:
    """Bounded HTTPS catalog client using the existing provider-egress checks."""

    TRANSIENT_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        if timeout_seconds <= 0 or max_attempts < 1:
            raise ValueError("catalog HTTP limits must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self._sleep = sleep
        self._random_uniform = random_uniform

    def discover(self, account: ProviderAccount, credential: str) -> list[DiscoveredModel]:
        """Fetch and normalize one account's model document with bounded retries."""
        if account.models_url is None:
            raise CatalogHttpError("catalog_endpoint_not_configured")
        for attempt in range(self.max_attempts):
            try:
                document = self._request_json(account, credential)
                models = normalize_models_document(document)
                if not models:
                    raise CatalogHttpError("catalog_contains_no_models")
                return models
            except CatalogHttpError as exc:
                if not exc.transient or attempt + 1 >= self.max_attempts:
                    raise
                ceiling = min(8.0, 0.5 * (2**attempt))
                self._sleep(self._random_uniform(0.0, ceiling))
        raise CatalogHttpError("catalog_attempts_exhausted", transient=True)

    def _request_json(self, account: ProviderAccount, credential: str) -> dict[str, Any]:
        """GET one catalog document after the existing provider-host safety checks."""
        if not account.models_path:
            raise CatalogHttpError("catalog_endpoint_not_configured")
        probe = ModelAgent(
            id="catalog_probe_agent",
            model="catalog_probe",
            base_url=account.base_url,
            credential_key=account.credential_name,
            provider_name=account.provider_name,
        )
        client = ModelClient(timeout=max(1, int(self.timeout_seconds)))
        client._validate_provider(probe)
        models_path = account.models_path if account.models_path.startswith("/") else f"/{account.models_path}"
        request = urllib.request.Request(
            client._provider_url(probe, models_path),
            headers={
                account.auth_header_name: f"{account.auth_prefix} {credential}".strip(),
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with client._open_provider(request) as response:
                raw_payload = response.read(CATALOG_RESPONSE_MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise CatalogHttpError("catalog_authentication_failed") from exc
            raise CatalogHttpError(
                f"catalog_http_{exc.code}", transient=exc.code in self.TRANSIENT_STATUS
            ) from exc
        except TimeoutError as exc:
            raise CatalogHttpError("catalog_timeout", transient=True) from exc
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError) or "timed out" in str(exc).lower():
                raise CatalogHttpError("catalog_timeout", transient=True) from exc
            raise CatalogHttpError("catalog_network_failure", transient=True) from exc
        if len(raw_payload) > CATALOG_RESPONSE_MAX_BYTES:
            raise CatalogHttpError("catalog_response_too_large")
        try:
            document = json.loads(raw_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            raise CatalogHttpError("catalog_json_invalid") from None
        if not isinstance(document, dict):
            raise CatalogHttpError("catalog_json_must_be_object")
        return document


class ProviderAwareModelClient(ModelClient):
    """OpenAI-compatible client plus a native Bytez Key/input adapter.

    Bytez is not treated as OpenAI ``/v1/chat/completions``. Unsupported
    passthrough shapes fail closed instead of fabricating an OpenAI object.
    """

    def __init__(
        self,
        *args: Any,
        bytez_request: Callable[[ModelAgent, list[dict[str, str]], str], Mapping[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._bytez_request = bytez_request or self._request_bytez

    def chat(self, agent: ModelAgent, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        """Dispatch Bytez through its native Key/input contract and delegate all peers."""
        if agent.provider_name != "bytez":
            return super().chat(agent, messages, temperature=temperature)
        self._local.usage = None
        credential = get_credential(agent.credential_name)
        if not credential:
            raise ProviderCatalogUnavailable("Bytez credential is not registered")
        document = self._bytez_request(agent, messages, credential)
        return _normalize_bytez_output(document)

    def stream_chat(self, agent: ModelAgent, messages: list[dict[str, str]], temperature: float = 0.2):
        """Frame a completed native Bytez answer when that API offers no token SSE contract."""
        if agent.provider_name != "bytez":
            yield from super().stream_chat(agent, messages, temperature=temperature)
            return
        answer = self.chat(agent, messages, temperature=temperature)
        for start in range(0, len(answer), 24):
            yield answer[start : start + 24]

    def proxy_send(self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Fail closed for unsupported Bytez passthrough instead of fabricating OpenAI shapes."""
        if agent.provider_name == "bytez":
            raise ProviderCatalogUnavailable(
                f"Bytez native transport does not support passthrough endpoint {endpoint}"
            )
        return super().proxy_send(agent, endpoint, payload)

    def _request_bytez(
        self,
        agent: ModelAgent,
        messages: list[dict[str, str]],
        credential: str,
    ) -> Mapping[str, Any]:  # pragma: no cover - real Bytez network boundary
        self._validate_provider(agent)
        model_path = quote(agent.model, safe="")
        request = urllib.request.Request(
            self._provider_url(agent, f"/models/v2/{model_path}"),
            data=json.dumps({"input": messages}).encode("utf-8"),
            headers={
                "Authorization": f"Key {credential}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with self._open_provider(request) as response:
            document = json.loads(response.read().decode("utf-8"))
        if not isinstance(document, dict):
            raise ProviderCatalogUnavailable("Bytez response shape is unsupported")
        return document


class ProviderCatalogService:
    """Coordinate isolated provider refreshes and build the runtime agent pool."""

    def __init__(
        self,
        *,
        store: ProviderCatalogStore,
        accounts: Sequence[ProviderAccount] = DEFAULT_PROVIDER_ACCOUNTS,
        discover: Callable[[ProviderAccount, str], Sequence[DiscoveredModel]] | None = None,
        min_refresh_interval_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = store
        self.accounts = tuple(accounts)
        self._account_by_id = {account.provider_account_id: account for account in self.accounts}
        self._discover = discover or ProviderCatalogHttpClient().discover
        self.min_refresh_interval_seconds = min_refresh_interval_seconds
        self._clock = clock
        self._last_refresh_at = 0.0
        self.last_refresh_summary: dict[str, Any] = {
            "provider_accounts": {},
            "candidate_model_count": 0,
            "measurement_status": "provider_catalog_snapshot",
        }

    def refresh_all(self, *, require_candidates: bool = True, force: bool = False) -> dict[str, Any]:
        """Refresh each account independently and preserve stale usable catalogs."""
        now = self._clock()
        if (
            not force
            and self._last_refresh_at > 0
            and (now - self._last_refresh_at) < self.min_refresh_interval_seconds
            and self.last_refresh_summary.get("provider_accounts")
        ):
            return {**self.last_refresh_summary, "refresh_status": "throttled"}

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
                    account, "credential_not_registered"
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
                provider_rows[account.provider_account_id] = self._failed_refresh(account, exc.code)
            except Exception:
                provider_rows[account.provider_account_id] = self._failed_refresh(
                    account, "catalog_adapter_failure"
                )
        candidates = self.store.enabled_models()
        self._last_refresh_at = now
        self.last_refresh_summary = {
            "provider_accounts": provider_rows,
            "candidate_model_count": len(candidates),
            "measurement_status": "provider_catalog_snapshot",
        }
        if require_candidates and not candidates:
            raise ProviderCatalogUnavailable("no usable provider model exists after catalog refresh")
        return self.last_refresh_summary

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
        """Convert enabled catalog rows into role-tagged agents. Price is not baked into priority."""
        agents: list[ModelAgent] = []
        for record in self.store.enabled_models():
            account = self._account_by_id[record.provider_account_id]
            model = record.model
            agents.append(
                ModelAgent(
                    id=_agent_id(account.provider_account_id, model.model_name),
                    model=model.model_name,
                    base_url=account.base_url,
                    credential_key=account.credential_name,
                    tags=_agent_tags(model),
                    priority=account.priority_rank,
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
    names only and is safe for CI logs. ``environment`` is bootstrap transport
    only — request-time resolution stays on :func:`get_credential`.
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
        if value:
            register_credential(account.credential_name, value)
            registered.append(account.credential_name)
    return {"registered_credentials": registered, "missing_credentials": missing}


def normalize_models_document(document: Mapping[str, Any]) -> list[DiscoveredModel]:
    """Normalize common OpenAI/OpenRouter/Bytez listing shapes into model rows.

    Channel prices (including explicit ``0``) are stored separately from list /
    original prices. Comparison prices prefer a known list price so a free
    channel does not win as cost ``0.0``. A list price is never invented: only
    documented per-million fields, finite OpenRouter ``pricing`` on the same
    row, or a same-document paid sibling (``:free`` suffix stripped) are used.
    """
    raw_rows: Any = document.get("data")
    if not isinstance(raw_rows, list):
        raw_rows = document.get("models")
    if isinstance(raw_rows, Mapping):
        raw_rows = list(raw_rows.values())
    if not isinstance(raw_rows, list):
        return []
    parsed_rows: dict[str, _ParsedCatalogRow] = {}
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
        channel_input = _first_known_usd(
            pricing.get("prompt"),
            raw.get("input_price_per_token"),
            per_token=True,
        )
        channel_output = _first_known_usd(
            pricing.get("completion"),
            raw.get("output_price_per_token"),
            per_token=True,
        )
        list_input = _first_known_usd(
            raw.get("list_input_usd_per_million"),
            raw.get("published_input_per_million"),
            raw.get("list_input_price_usd_per_million"),
        )
        list_output = _first_known_usd(
            raw.get("list_output_usd_per_million"),
            raw.get("published_output_per_million"),
            raw.get("list_output_price_usd_per_million"),
        )
        if list_input is None:
            list_input = _first_known_usd(
                pricing.get("list_prompt"),
                pricing.get("original_prompt"),
                per_token=True,
            )
        if list_output is None:
            list_output = _first_known_usd(
                pricing.get("list_completion"),
                pricing.get("original_completion"),
                per_token=True,
            )
        if list_input is None and channel_input is not None and channel_input > 0:
            list_input = channel_input
        if list_output is None and channel_output is not None and channel_output > 0:
            list_output = channel_output
        parsed_rows[name] = _ParsedCatalogRow(
            model_name=name,
            display_name=display_name,
            capabilities=capabilities,
            modalities=modalities,
            context_window=context_window,
            channel_input=channel_input,
            channel_output=channel_output,
            list_input=list_input,
            list_output=list_output,
        )
    for row in parsed_rows.values():
        sibling_name = _paid_sibling_name(row.model_name)
        if sibling_name is None:
            continue
        sibling = parsed_rows.get(sibling_name)
        if sibling is None:
            continue
        if row.list_input is None and sibling.list_input is not None:
            row.list_input = sibling.list_input
        if row.list_output is None and sibling.list_output is not None:
            row.list_output = sibling.list_output
    models = [
        DiscoveredModel(
            model_name=row.model_name,
            display_name=row.display_name,
            capabilities=row.capabilities,
            modalities=row.modalities,
            context_window=row.context_window,
            input_price_usd_per_million=_comparison_catalog_price(row.list_input, row.channel_input),
            output_price_usd_per_million=_comparison_catalog_price(row.list_output, row.channel_output),
            channel_input_usd_per_million=row.channel_input,
            channel_output_usd_per_million=row.channel_output,
            list_input_usd_per_million=row.list_input,
            list_output_usd_per_million=row.list_output,
        )
        for row in parsed_rows.values()
    ]
    return sorted(models, key=lambda model: model.model_name)


def known_catalog_prices(store: ProviderCatalogStore) -> dict[str, float]:
    """Return finite nonnegative catalog prices keyed by model name.

    Prefer a known list/original price over the current channel price so a
    served-free listing does not win as cost ``0.0``. Explicit channel ``0``
    with no list price remains a known price of ``0``. Missing, negative, or
    non-finite catalog prices are omitted — they are not converted to zero.
    """
    prices: dict[str, float] = {}
    for row in store.enabled_models():
        price = _model_comparison_price(row.model)
        if price is not None:
            prices[row.model.model_name] = price
    return prices


def refresh_and_overlay(
    orchestrator: TaskOrchestrator,
    service: ProviderCatalogService | None = None,
    *,
    require_candidates: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Refresh the catalog and overlay discovered workers onto ``orchestrator``.

    Overlay mode (default) records failures in audit and keeps the seed pool
    when discovery yields nothing. Catalog-only callers pass
    ``require_candidates=True`` to fail closed on an empty first refresh.
    """
    active = service or getattr(orchestrator, "catalog_service", None) or ProviderCatalogService(
        store=InMemoryProviderCatalogStore()
    )
    orchestrator.catalog_service = active
    try:
        summary = active.refresh_all(require_candidates=require_candidates, force=force)
    except ProviderCatalogUnavailable as exc:
        orchestrator._append_audit_event(
            "catalog_refresh_failed",
            {"error_code": str(exc), **active.last_refresh_summary},
        )
        raise
    agents = active.candidate_agents()
    overlay = orchestrator.overlay_discovered_agents(agents, known_catalog_prices(active.store))
    orchestrator._append_audit_event(
        "catalog_refresh_completed",
        {**summary, **overlay},
    )
    return {**summary, **overlay}


def build_catalog_orchestrator(
    store: ProviderCatalogStore,
    *,
    accounts: Sequence[ProviderAccount] = DEFAULT_PROVIDER_ACCOUNTS,
    client: ModelClient | None = None,
    **orchestrator_options: Any,
) -> TaskOrchestrator:
    """Build a normal :class:`TaskOrchestrator` from the discovered candidate pool."""
    service = ProviderCatalogService(store=store, accounts=accounts)
    agents = service.candidate_agents()
    if not agents:
        raise ProviderCatalogUnavailable("provider catalog contains no enabled agents")
    return TaskOrchestrator(
        agents,
        client=client or ProviderAwareModelClient(),
        price_per_million=known_catalog_prices(store),
        **orchestrator_options,
    )


def _normalize_bytez_output(document: Mapping[str, Any]) -> str:
    """Extract text from the bounded native Bytez response contract."""
    output = document.get("output")
    if isinstance(output, str) and output:
        return output
    if isinstance(output, Mapping):
        content = output.get("content") or output.get("text")
        if isinstance(content, str) and content:
            return content
    raise ProviderCatalogUnavailable("Bytez response shape is unsupported")


def _infer_capabilities(
    model_name: str,
    raw: Mapping[str, Any],
    modalities: Sequence[str],
) -> tuple[str, ...]:
    """Infer conservative routing tags from provider metadata and model naming."""
    lowered = model_name.lower()
    capabilities = {value.lower() for value in _string_values(raw.get("capabilities"))}
    if any(token in lowered for token in ("embed", "embedding")):
        capabilities.add("embeddings")
    elif "rerank" in lowered:
        capabilities.add("reranking")
    elif "moderation" in lowered:
        capabilities.add("moderation")
    else:
        capabilities.add("chat")
    if any(token in lowered for token in ("reason", "o1", "o3", "r1", "thinking")):
        capabilities.add("reasoning")
    if any(token in lowered for token in ("code", "coder", "codestral", "devstral")):
        capabilities.add("coding")
    if "image" in modalities or "vision" in lowered or "vl" in lowered:
        capabilities.add("vision")
    if "audio" in modalities or any(token in lowered for token in ("audio", "whisper", "speech")):
        capabilities.add("audio")
    if "guard" in lowered:
        capabilities.add("moderation")
    return tuple(sorted(capabilities))


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


def _agent_id(provider_account_id: str, model_name: str) -> str:
    """Create a bounded two-or-more-word snake-case agent identifier."""
    slug = re.sub(r"[^a-z0-9]+", "_", model_name.lower()).strip("_") or "model_worker"
    digest = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:8]
    return f"{provider_account_id}_{slug}_{digest}"[:120].rstrip("_")


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
    return parsed if 0 < parsed <= 10_000_000_000 else None


@dataclass
class _ParsedCatalogRow:
    """Mutable first-pass catalog row used to attach same-document list prices."""

    model_name: str
    display_name: str
    capabilities: tuple[str, ...]
    modalities: tuple[str, ...]
    context_window: int | None
    channel_input: float | None
    channel_output: float | None
    list_input: float | None
    list_output: float | None


def _paid_sibling_name(model_name: str) -> str | None:
    """Return the same-document paid id for an OpenRouter ``:free`` variant."""
    suffix = ":free"
    if model_name.endswith(suffix) and len(model_name) > len(suffix):
        return model_name[: -len(suffix)]
    return None


def _known_usd_amount(value: Any) -> float | None:
    """Return a finite nonnegative USD amount, or ``None`` when unpriced."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _first_known_usd(*values: Any, per_token: bool = False) -> float | None:
    """Return the first documented finite nonnegative price, optionally scaled."""
    for value in values:
        parsed = _known_usd_amount(value)
        if parsed is None:
            continue
        return parsed * 1_000_000 if per_token else parsed
    return None


def _comparison_catalog_price(list_price: float | None, channel_price: float | None) -> float | None:
    """Prefer a known list/original price; fall back to an explicit channel price."""
    if known_price_rank(list_price)[0]:
        return float(list_price)
    if known_price_rank(channel_price)[0]:
        return float(channel_price)
    return None


def _model_comparison_price(model: DiscoveredModel) -> float | None:
    """Resolve the honest comparison price from list, then comparison, then channel."""
    for candidate in (
        model.list_output_usd_per_million,
        model.list_input_usd_per_million,
        model.output_price_usd_per_million,
        model.input_price_usd_per_million,
        model.channel_output_usd_per_million,
        model.channel_input_usd_per_million,
    ):
        if known_price_rank(candidate)[0]:
            return float(candidate)
    return None


def _per_token_price_to_million(value: Any) -> float | None:
    """Convert a finite non-negative per-token USD price to per-million units."""
    return _first_known_usd(value, per_token=True)


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _utc_now_text() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return _utc_now().isoformat()
