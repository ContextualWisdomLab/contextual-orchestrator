"""Provider discovery, model eligibility, and runtime-agent construction.

The catalog turns a fixed deploy-time credential inventory into an auditable
runtime model pool. Provider values enter the existing credential registry only
through a trusted bootstrap process. Runtime agents and catalog metadata retain
credential names, never secret values.

Provider refreshes are account-scoped. A failure records a stable error code and
preserves that account's last-known-good models. A first deployment with no
eligible chat model fails closed instead of silently starting a mock or empty
pool.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
import random
import re
import sys
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence
from urllib.parse import quote

from .credentials import get_credential, register_credential
from .orchestrator import ModelAgent, ModelClient, TaskOrchestrator


SERVING_CAPABILITIES = frozenset({"chat", "reasoning", "coding"})
"""Capabilities eligible for the chat orchestration pool."""


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
    """Provider-neutral metadata for one discovered provider model."""

    model_name: str
    display_name: str
    capabilities: tuple[str, ...] = ("unknown",)
    modalities: tuple[str, ...] = ("text",)
    context_window: int | None = None
    input_price_usd_per_million: float | None = None
    output_price_usd_per_million: float | None = None


@dataclass(frozen=True)
class CatalogModelRecord:
    """One discovered model associated with its provider account."""

    provider_account_id: str
    model: DiscoveredModel


class ProviderCatalogUnavailable(RuntimeError):
    """Raised when the authoritative provider catalog cannot serve a request."""


class CatalogHttpError(RuntimeError):
    """Stable, secret-free provider catalog transport failure."""

    def __init__(
        self,
        code: str,
        *,
        transient: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient
        self.retry_after_seconds = retry_after_seconds


class ProviderCatalogStore(Protocol):
    """Persistence contract shared by standalone and PostgreSQL deployments."""

    def upsert_account(self, account: ProviderAccount) -> None:
        """Insert or update one provider account without a secret value."""
        ...

    def replace_catalog(self, account: ProviderAccount, models: Sequence[DiscoveredModel]) -> None:
        """Atomically replace one successful account's current model set."""
        ...

    def record_failure(self, account: ProviderAccount, error_code: str) -> None:
        """Record a failed refresh without changing last-known-good models."""
        ...

    def enabled_models(self) -> list[CatalogModelRecord]:
        """Return enabled models belonging to enabled provider accounts."""
        ...

    def all_models(self) -> list[CatalogModelRecord]:
        """Return retained models including disabled-account history."""
        ...

    def has_models(self, provider_account_id: str) -> bool:
        """Return whether an account retains an enabled model."""
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
    ),
    ProviderAccount(
        provider_account_id="bytez_primary",
        provider_name="bytez",
        credential_name="BYTEZ_API_KEY",
        base_url="https://api.bytez.com",
        models_path="/models/v2",
        transport_name="bytez_v2",
        auth_prefix="Key",
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
"""Fixed account inventory corresponding to the five organization secrets."""


class InMemoryProviderCatalogStore:
    """Thread-safe deterministic catalog store for tests and local evaluation."""

    def __init__(self) -> None:
        self._accounts: dict[str, ProviderAccount] = {}
        self._models: dict[str, dict[str, DiscoveredModel]] = {}
        self.refresh_runs: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def upsert_account(self, account: ProviderAccount) -> None:
        """Store an account definition while preserving its model history."""
        with self._lock:
            self._accounts[account.provider_account_id] = account

    def replace_catalog(self, account: ProviderAccount, models: Sequence[DiscoveredModel]) -> None:
        """Replace one account catalog and append successful refresh evidence."""
        unique = {model.model_name: model for model in models if model.model_name}
        now = _utc_now_text()
        with self._lock:
            self._accounts[account.provider_account_id] = account
            self._models[account.provider_account_id] = unique
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
        """Append failure evidence while preserving the prior model mapping."""
        now = _utc_now_text()
        with self._lock:
            self._accounts[account.provider_account_id] = account
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
        """Return sorted current model rows for enabled provider accounts."""
        with self._lock:
            records = [
                CatalogModelRecord(account_id, model)
                for account_id, models in self._models.items()
                if self._accounts[account_id].enabled
                for model in models.values()
            ]
        return sorted(records, key=lambda row: (row.provider_account_id, row.model.model_name))

    def all_models(self) -> list[CatalogModelRecord]:
        """Return all retained model rows regardless of account enablement."""
        with self._lock:
            records = [
                CatalogModelRecord(account_id, model)
                for account_id, models in self._models.items()
                for model in models.values()
            ]
        return sorted(records, key=lambda row: (row.provider_account_id, row.model.model_name))

    def has_models(self, provider_account_id: str) -> bool:
        """Return whether an account has at least one retained model."""
        with self._lock:
            return bool(self._models.get(provider_account_id))


class ProviderCatalogHttpClient:
    """Bounded HTTPS client policy for provider model listings."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        max_attempts: int = 3,
        deadline_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_seconds <= 0 or max_attempts < 1 or deadline_seconds <= 0:
            raise ValueError("catalog HTTP limits must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.deadline_seconds = deadline_seconds
        self._sleep = sleep
        self._random_uniform = random_uniform
        self._clock = clock

    def discover(self, account: ProviderAccount, credential: str) -> list[DiscoveredModel]:
        """Fetch and normalize one account's model document with bounded retries."""
        if account.models_url is None:
            raise CatalogHttpError("catalog_endpoint_not_configured")
        started_at = self._clock()
        for attempt in range(self.max_attempts):
            if self._clock() - started_at >= self.deadline_seconds:
                raise CatalogHttpError("catalog_deadline_exceeded", transient=True)
            try:
                document = self._request_json(account, credential)
                models = normalize_models_document(document)
                if not models:
                    raise CatalogHttpError("catalog_contains_no_models")
                return models
            except CatalogHttpError as exc:
                if not exc.transient or attempt + 1 >= self.max_attempts:
                    raise
                remaining = max(0.0, self.deadline_seconds - (self._clock() - started_at))
                if exc.retry_after_seconds is None:
                    requested = self._random_uniform(0.0, min(8.0, 0.5 * (2**attempt)))
                else:
                    requested = exc.retry_after_seconds
                delay = min(30.0, remaining, max(0.0, requested))
                if delay:
                    self._sleep(delay)
        raise CatalogHttpError("catalog_attempts_exhausted", transient=True)

    def _request_json(self, account: ProviderAccount, credential: str) -> dict[str, Any]:  # pragma: no cover
        from .provider_catalog_transport import secure_json_request

        return secure_json_request(
            method="GET",
            url=account.models_url or "",
            header_name=account.auth_header_name,
            authorization=f"{account.auth_prefix} {credential}".strip(),
            payload=None,
            timeout_seconds=self.timeout_seconds,
        )


class ProviderAwareModelClient(ModelClient):
    """Use hardened OpenAI-compatible transport plus a native Bytez adapter."""

    def __init__(
        self,
        *args: Any,
        bytez_request: Callable[[ModelAgent, str, str], Mapping[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._bytez_request = bytez_request or self._request_bytez

    def chat(self, agent: ModelAgent, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        """Dispatch Bytez through its native Key/input contract and delegate peers."""
        if agent.provider_name != "bytez":
            return super().chat(agent, messages, temperature=temperature)
        self._local.usage = None
        credential = get_credential(agent.credential_name)
        if not credential:
            raise ProviderCatalogUnavailable("Bytez credential is not registered")
        document = self._bytez_request(agent, _messages_to_prompt(messages), credential)
        return _normalize_bytez_output(document)

    def stream_chat(self, agent: ModelAgent, messages: list[dict[str, str]], temperature: float = 0.2):
        """Frame completed Bytez text when no verified native SSE contract exists."""
        if agent.provider_name != "bytez":
            yield from super().stream_chat(agent, messages, temperature=temperature)
            return
        answer = self.chat(agent, messages, temperature=temperature)
        for start in range(0, len(answer), 24):
            yield answer[start : start + 24]

    def proxy_send(self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Fail closed for unsupported Bytez passthrough instead of guessing shapes."""
        if agent.provider_name == "bytez":
            raise ProviderCatalogUnavailable(
                f"Bytez native transport does not support passthrough endpoint {endpoint}"
            )
        return super().proxy_send(agent, endpoint, payload)

    def _request_bytez(self, agent: ModelAgent, prompt: str, credential: str) -> Mapping[str, Any]:  # pragma: no cover
        from .provider_catalog_transport import secure_json_request

        return secure_json_request(
            method="POST",
            url=f"{agent.base_url.rstrip('/')}/models/v2/{quote(agent.model, safe='')}",
            header_name="Authorization",
            authorization=f"Key {credential}",
            payload={"input": prompt},
            timeout_seconds=float(self.timeout),
        )


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
        self._discover = discover or ProviderCatalogHttpClient().discover
        self.last_refresh_summary: dict[str, Any] = {
            "provider_accounts": {},
            "candidate_model_count": 0,
            "measurement_status": "provider_catalog_snapshot",
        }

    def refresh_all(self) -> dict[str, Any]:
        """Refresh accounts independently and preserve stale usable catalogs."""
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
        candidates = self.candidate_agents()
        self.last_refresh_summary = {
            "provider_accounts": provider_rows,
            "candidate_model_count": len(candidates),
            "measurement_status": "provider_catalog_snapshot",
        }
        if not candidates:
            raise ProviderCatalogUnavailable(
                "no usable chat-capable provider model exists after catalog refresh"
            )
        return self.last_refresh_summary

    def _failed_refresh(self, account: ProviderAccount, code: str) -> dict[str, Any]:
        """Record failure and classify whether last-known-good data remains."""
        self.store.record_failure(account, code)
        return {
            "status": "stale_available" if self.store.has_models(account.provider_account_id) else "failed",
            "model_count": 0,
            "error_code": code,
        }

    def candidate_agents(self) -> list[ModelAgent]:
        """Convert eligible catalog rows into role-tagged model agents."""
        agents: list[ModelAgent] = []
        for record in self.store.enabled_models():
            model = record.model
            if not SERVING_CAPABILITIES.intersection(model.capabilities):
                continue
            account = self._account_by_id.get(record.provider_account_id)
            if account is None or not account.enabled:
                continue
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
    """Transport a validated provider-secret inventory into the credential KV.

    Required bootstrap validates the whole fixed inventory before mutation,
    preventing a partially rotated production credential generation. Returned
    summaries contain credential names only.
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
    """Normalize common provider listing shapes without inventing metadata."""
    raw_rows: Any = document.get("data")
    if not isinstance(raw_rows, list):
        raw_rows = document.get("models")
    if isinstance(raw_rows, Mapping):
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
        pricing = raw.get("pricing") if isinstance(raw.get("pricing"), Mapping) else {}
        models[name] = DiscoveredModel(
            model_name=name,
            display_name=display_name,
            capabilities=_infer_capabilities(name, raw, modalities),
            modalities=modalities,
            context_window=_optional_positive_int(
                raw.get("context_length") or raw.get("context_window") or raw.get("max_context_length")
            ),
            input_price_usd_per_million=_per_token_price_to_million(
                pricing.get("prompt") or raw.get("input_price_per_token")
            ),
            output_price_usd_per_million=_per_token_price_to_million(
                pricing.get("completion") or raw.get("output_price_per_token")
            ),
        )
    return [models[name] for name in sorted(models)]


def build_catalog_orchestrator(
    store: ProviderCatalogStore,
    *,
    accounts: Sequence[ProviderAccount] = DEFAULT_PROVIDER_ACCOUNTS,
    client: ModelClient | None = None,
    **orchestrator_options: Any,
) -> TaskOrchestrator:
    """Build :class:`TaskOrchestrator` from enabled durable candidates."""
    agents = ProviderCatalogService(store=store, accounts=accounts).candidate_agents()
    if not agents:
        raise ProviderCatalogUnavailable("provider catalog contains no enabled chat-capable agents")
    return TaskOrchestrator(
        agents,
        client=client or ProviderAwareModelClient(),
        **orchestrator_options,
    )


def _messages_to_prompt(messages: Sequence[Mapping[str, Any]]) -> str:
    """Serialize text-only chat messages for a native text-generation endpoint."""
    lines: list[str] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if not isinstance(role, str) or not role or not isinstance(content, str):
            raise ProviderCatalogUnavailable("Bytez native chat requires text-only role/content messages")
        lines.append(f"{role.strip().lower()}: {content}")
    if not lines:
        raise ProviderCatalogUnavailable("Bytez native chat requires at least one message")
    lines.append("assistant:")
    return "\n".join(lines)


def _normalize_bytez_output(document: Mapping[str, Any]) -> str:
    """Extract text from conservative native Bytez response shapes."""
    output: Any = document.get("output")
    candidates: list[Any] = [output]
    if isinstance(output, Sequence) and not isinstance(output, (str, bytes, bytearray)):
        candidates.extend(output[:1])
    candidates.extend(document.get(name) for name in ("content", "text", "generated_text"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
        if isinstance(candidate, Mapping):
            for name in ("content", "text", "generated_text"):
                value = candidate.get(name)
                if isinstance(value, str) and value:
                    return value
    raise ProviderCatalogUnavailable("Bytez response shape is unsupported")


def _infer_capabilities(
    model_name: str,
    raw: Mapping[str, Any],
    modalities: Sequence[str],
) -> tuple[str, ...]:
    """Infer conservative capabilities from provider metadata and model naming."""
    declared = {value.lower() for value in _string_values(raw.get("capabilities"))}
    if declared:
        capabilities = declared
    else:
        lowered = model_name.lower()
        specialized: tuple[tuple[tuple[str, ...], str], ...] = (
            (("embed", "embedding"), "embeddings"),
            (("rerank",), "reranking"),
            (("moderation", "guard", "reward", "classifier"), "moderation"),
            (("whisper", "transcription", "speech-to-text"), "transcription"),
            (("tts", "text-to-speech"), "speech_generation"),
            (("gpt-image", "dall-e", "image-generation", "stable-diffusion", "flux"), "image_generation"),
            (("sora", "video-generation"), "video_generation"),
        )
        capabilities = set()
        for tokens, capability in specialized:
            if any(token in lowered for token in tokens):
                capabilities.add(capability)
                break
        if not capabilities and any(
            token in lowered
            for token in (
                "gpt",
                "chat",
                "instruct",
                "llama",
                "qwen",
                "mistral",
                "mixtral",
                "gemma",
                "phi",
                "deepseek",
                "command",
                "nemotron",
                "claude",
                "grok",
                "glm",
                "reason",
                "coder",
                "codestral",
                "devstral",
                "o1",
                "o3",
            )
        ):
            capabilities.add("chat")
        if not capabilities:
            capabilities.add("unknown")
    lowered = model_name.lower()
    if "chat" in capabilities and any(
        token in lowered for token in ("reason", "thinking", "deepseek-r", "o1", "o3")
    ):
        capabilities.add("reasoning")
    if "chat" in capabilities and any(
        token in lowered for token in ("code", "coder", "codestral", "devstral")
    ):
        capabilities.add("coding")
    if "chat" in capabilities and ("image" in modalities or "vision" in lowered or "-vl" in lowered):
        capabilities.add("vision")
    if "chat" in capabilities and "audio" in modalities:
        capabilities.add("audio")
    return tuple(sorted(capabilities))


def _agent_tags(model: DiscoveredModel) -> tuple[str, ...]:
    """Map provider capabilities into the orchestrator role/domain vocabulary."""
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
    """Use context and known price only as bounded ties after capability fit."""
    context_tie = min(2, (model.context_window or 0) // 200_000)
    known_prices = [
        value
        for value in (
            model.input_price_usd_per_million,
            model.output_price_usd_per_million,
        )
        if value is not None
    ]
    price_tie = 1 if known_prices and sum(known_prices) / len(known_prices) < 1.0 else 0
    return context_tie + price_tie


def _agent_id(provider_account_id: str, model_name: str) -> str:
    """Create a bounded two-or-more-word snake-case agent identifier."""
    slug = re.sub(r"[^a-z0-9]+", "_", model_name.lower()).strip("_") or "model_worker"
    digest = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:8]
    return f"{provider_account_id}_{slug}_{digest}"[:120].rstrip("_")


def _refresh_id(account_id: str, timestamp: str) -> str:
    """Return an immutable refresh identifier without credential material."""
    material = f"{account_id}\0{timestamp}".encode("utf-8")
    return f"catalog_refresh_{hashlib.sha256(material).hexdigest()}"


def _string_values(value: Any) -> list[str]:
    """Return bounded non-empty strings from scalar or sequence metadata."""
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
    """Return a bounded positive integer, rejecting booleans and overflow."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if 0 < parsed <= 10_000_000_000 else None


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


def _utc_now_text() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _safe_cli_summary(credential_summary: Mapping[str, Any], catalog_summary: Mapping[str, Any]) -> dict[str, Any]:
    """Build a log-safe bootstrap summary containing names and counts only."""
    return {
        "registered_credentials": list(credential_summary.get("registered_credentials", [])),
        "missing_credentials": list(credential_summary.get("missing_credentials", [])),
        "candidate_model_count": int(catalog_summary.get("candidate_model_count", 0)),
        "provider_accounts": dict(catalog_summary.get("provider_accounts", {})),
        "measurement_status": "provider_catalog_bootstrap",
    }


def _write_agents_file(path: str, agents: Sequence[ModelAgent]) -> None:  # pragma: no cover
    """Atomically write a secret-free agent configuration JSON document."""
    target = os.path.abspath(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    temporary = f"{target}.tmp-{os.getpid()}"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(
                {"agents": [agent.to_config() for agent in agents]},
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover
    """Bootstrap credentials, refresh the durable catalog, and export agents."""
    from .provider_catalog_postgres import PostgresProviderCatalogStore

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
        credential_summary = bootstrap_provider_credentials(os.environ, require_all=args.require_all)
    service = ProviderCatalogService(store=store)
    if args.command in {"bootstrap-and-sync", "sync"}:
        catalog_summary = service.refresh_all()
    else:
        catalog_summary = {
            "candidate_model_count": len(service.candidate_agents()),
            "provider_accounts": {},
        }
    agents = service.candidate_agents()
    if not agents:
        raise ProviderCatalogUnavailable("provider catalog contains no enabled chat-capable agents")
    if args.agents_output:
        _write_agents_file(args.agents_output, agents)
    print(json.dumps(_safe_cli_summary(credential_summary, catalog_summary), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except ProviderCatalogUnavailable as exc:
        print(
            json.dumps({"error": "provider_catalog_unavailable", "message": str(exc)}),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
