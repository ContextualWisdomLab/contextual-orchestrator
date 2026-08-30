"""Provider model-list discovery: turns registered KV credentials into agent candidates.

Queries each configured provider's model-list endpoint over its OpenAI-compatible
(or provider-specific) discovery API and returns :class:`DiscoveredModel` rows that
callers turn into :class:`~contextual_orchestrator.orchestrator.ModelAgent` entries
and/or :class:`~contextual_orchestrator.cost_ledger.PriceBook` rows.

Credentials are never fabricated: a provider resolves through :func:`get_credential`
(the KV registry), and a provider with nothing registered is silently skipped so
registering a subset of the declared provider keys still works. Stdlib only
(``urllib.request``), matching this repo's dependency-free transport convention.
"""

from __future__ import annotations

from decimal import Decimal
import json
import math
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from .chat_capability import is_general_chat_agent_model_id, is_general_chat_candidate
from .credentials import get_credential
from .orchestrator import ModelAgent

if TYPE_CHECKING:
    from .cost_ledger import PriceBook

DISCOVERY_TIMEOUT_SECONDS = 15.0
# Some discovery endpoints (verified live: models.dev returns Cloudflare HTTP
# 403 error 1010) reject urllib's default "Python-urllib/X.Y" user agent as a
# bot signature. A stable, identifying user agent is not a credential and is
# safe to send on every request, authenticated or not.
_HTTP_USER_AGENT = "contextual-orchestrator/0.2.0 (+https://github.com/ContextualWisdomLab/contextual-orchestrator)"
_CAPABILITY_NAMES = {"embeddings": "embedding"}
_MODELS_DEV_URL = "https://models.dev/api.json"
# Small bounded retry budget for the one shared, unauthenticated, third-party
# Models.dev fetch that every ``models_dev_provider_id``-joined source's
# free-tier classification depends on (ADR 0041/0032). It has already been
# observed live to reject urllib's default user agent as a bot signature (see
# ``_HTTP_USER_AGENT`` above); a lone transient failure of that kind must not
# silently erase every dependent provider's ``orchestrator/free`` coverage for
# the whole discovery run the way a single un-retried attempt would.
_MODELS_DEV_FETCH_ATTEMPTS = 3
_MODELS_DEV_FETCH_RETRY_DELAY_SECONDS = 0.05
# Sentinel distinguishing "no shared Models.dev payload supplied" (fall back to
# a lazy per-call fetch) from an explicitly supplied ``None`` -- the honest
# outcome of a real fetch failure. Never compare to it with ``==``.
_NOT_FETCHED = object()
_OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"


def _provider_discovery_error_code(exc: Exception) -> str:
    """Map provider failures to stable codes without retaining provider response text."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"http_status_{exc.code}"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        return "transport_error"
    if isinstance(exc, (ConnectionError, OSError)):
        # Raw connection resets/failures that are not URLError still count as
        # transport failures so callers see one stable code, never provider text.
        return "transport_error"
    if isinstance(exc, ValueError):
        return "invalid_response"
    # The sole caller catches exactly (URLError, TimeoutError, ValueError,
    # OSError) plus HTTPError (a URLError subtype), every one of which is
    # classified above. Reaching this point means the catch tuple drifted;
    # fail loudly instead of silently labeling an unclassified failure.
    raise AssertionError(f"unclassified provider discovery failure: {exc!r}")


@dataclass(frozen=True)
class ProviderModelSource:
    """Where and how to discover one provider's models."""

    provider_name: str
    credential_name: str
    list_url: str
    chat_base_url: str
    auth_scheme: str = "Bearer"
    style: str = "openai_compatible"  # or "bytez"
    task_filter: str = ""
    capabilities: tuple[str, ...] = ()
    bootstrap_required: bool = True
    evidence_only: bool = False
    models_dev_provider_id: str | None = None


# NVIDIA NIM is listed twice under two KV credential names (primary + sub) so both
# keys participate in upstream load balancing without a second provider identity.
PROVIDER_MODEL_SOURCES: tuple[ProviderModelSource, ...] = (
    ProviderModelSource(
        provider_name="openai",
        credential_name="OPENAI_API_KEY",
        list_url="https://api.openai.com/v1/models",
        chat_base_url="https://api.openai.com/v1",
        models_dev_provider_id="openai",
    ),
    ProviderModelSource(
        provider_name="openrouter",
        credential_name="OPENROUTER_API_KEY",
        list_url="https://openrouter.ai/api/v1/models?output_modalities=all",
        chat_base_url="https://openrouter.ai/api/v1",
        capabilities=("chat",),
        evidence_only=True,
    ),
    ProviderModelSource(
        provider_name="opencode_zen",
        credential_name="OPENCODE_ZEN_API_KEY",
        list_url="https://opencode.ai/zen/v1/models",
        chat_base_url="https://opencode.ai/zen/v1",
        capabilities=("chat",),
        bootstrap_required=False,
        models_dev_provider_id="opencode",
    ),
    ProviderModelSource(
        provider_name="nvidia_nim",
        credential_name="NVIDIA_NIM_API_KEY",
        list_url="https://integrate.api.nvidia.com/v1/models",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        capabilities=("chat",),
        models_dev_provider_id="nvidia",
    ),
    ProviderModelSource(
        provider_name="nvidia_nim_sub",
        credential_name="NVIDIA_NIM_API_KEY_SUB",
        list_url="https://integrate.api.nvidia.com/v1/models",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        capabilities=("chat",),
        models_dev_provider_id="nvidia",
    ),
    ProviderModelSource(
        provider_name="bytez",
        credential_name="BYTEZ_API_KEY",
        list_url="https://api.bytez.com/models/v2/list/models",
        chat_base_url="https://api.bytez.com/models/v2/openai/v1",
        auth_scheme="Key",
        style="bytez",
        task_filter="chat",
        capabilities=("chat",),
    ),
)

OPENROUTER_ZDR_ENDPOINTS_URL = "https://openrouter.ai/api/v1/endpoints/zdr"


@dataclass(frozen=True)
class DiscoveredModel:
    """One general-chat model found on a provider, with reported pricing."""

    provider_name: str
    model_id: str
    credential_name: str
    chat_base_url: str
    auth_scheme: str
    capabilities: tuple[str, ...] = ()
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()
    prompt_price_per_1k: float | None = None
    completion_price_per_1k: float | None = None
    currency_code: str = "USD"
    is_free: bool = False
    zdr_capable: bool = False
    evidence_only: bool = False


class ProviderDiscoveryError(RuntimeError):
    """Raised when a provider's model list could not be fetched (network/auth failure)."""

    def __init__(self, provider_name: str, error_code: str) -> None:
        self.provider_name = provider_name
        self.error_code = error_code
        super().__init__(f"model discovery failed for provider {provider_name!r}: {error_code}")


def _fetch_json(url: str, *, api_key: str = "", auth_scheme: str = "Bearer", timeout: float) -> Any:
    if not url.startswith("https://"):
        # Every caller passes one of the hardcoded PROVIDER_SOURCES chat_base_url
        # constants below, never external input -- but urlopen also honors
        # file:// and other unsafe schemes, so refuse anything not https as a
        # cheap invariant check rather than trusting the constant list alone.
        raise ValueError(f"refusing non-https model discovery URL: {url!r}")
    headers = {"user-agent": _HTTP_USER_AGENT}
    if api_key:
        headers["authorization"] = f"{auth_scheme} {api_key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    # Scheme is enforced to https:// immediately above; url is never attacker-controlled.
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https provider hosts  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        return json.loads(response.read().decode("utf-8"))


def _fetch_models_dev_metadata(*, timeout: float) -> Any | None:
    """Fetch the shared Models.dev catalog with a small bounded retry.

    Every ``models_dev_provider_id``-joined source (``opencode_zen``,
    ``nvidia_nim``, ``nvidia_nim_sub``, ``openai``) shares this one
    unauthenticated, best-effort, third-party fetch for its free-cost
    evidence; none of those providers report their own pricing, so a lone
    transient failure here (a timeout, a reset connection, or the
    bot-signature rejection ``_HTTP_USER_AGENT`` already guards against) used
    to silently degrade every one of them to ``is_free = False`` for the rest
    of the discovery run, collapsing ``orchestrator/free`` coverage over a
    blip in a service this gateway does not control.

    Returns ``None`` -- the existing "no evidence" fail-closed signal
    :func:`_merge_models_dev_metadata` already handles -- only once every
    bounded attempt has failed; a successful attempt returns immediately
    without spending the rest of the retry budget.
    """
    for attempt in range(_MODELS_DEV_FETCH_ATTEMPTS):
        try:
            return _fetch_json(_MODELS_DEV_URL, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            if attempt < _MODELS_DEV_FETCH_ATTEMPTS - 1:
                time.sleep(_MODELS_DEV_FETCH_RETRY_DELAY_SECONDS)
    return None


def _valid_price_component(value: object) -> bool:
    """Return whether one price component is finite, numeric, and non-negative."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(numeric) and numeric >= 0.0


def _price_per_1k(value: Any) -> float | None:
    """Convert a trustworthy per-token USD price to per-1K, else return unknown.

    Parses through ``Decimal`` first so a nonzero price that underflows to
    ``0.0`` in float (e.g. a stray ``1e-10000``) is rejected as unknown
    rather than silently accepted as a legitimate free price.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal_per_1k = Decimal(str(value)) * 1000
        per_1k = float(decimal_per_1k)
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not decimal_per_1k.is_finite() or (decimal_per_1k != 0 and per_1k == 0):
        return None
    return per_1k if _valid_price_component(per_1k) else None


def _serving_identity(model: DiscoveredModel) -> tuple[str, str]:
    """Return the durable agent identity used by discovery synchronization."""
    return (model.provider_name, model.model_id)


def _source_tiebreaker(model: DiscoveredModel) -> tuple[str, str, str, str]:
    """Choose deterministic transport metadata for an ambiguous duplicate row."""
    return (
        model.credential_name,
        model.chat_base_url,
        model.auth_scheme,
        model.currency_code,
    )


def _deduplicate_discovered_models(
    discovered: list[DiscoveredModel],
) -> list[DiscoveredModel]:
    """Collapse duplicate agent identities and withhold conflicting price evidence.

    Exact duplicate catalog rows become one candidate. When the same provider/model
    identity is repeated with conflicting metadata or prices, one deterministic
    transport record is retained but its prices become unknown. Provider row order
    therefore cannot fabricate a cheaper bootstrap candidate or consume failover
    capacity twice.
    """
    unique: dict[tuple[str, str], DiscoveredModel] = {}
    for model in discovered:
        identity = _serving_identity(model)
        previous = unique.get(identity)
        if previous is None:
            unique[identity] = model
            continue
        if previous == model:
            continue
        chosen = min((previous, model), key=_source_tiebreaker)
        unique[identity] = replace(
            chosen,
            prompt_price_per_1k=None,
            completion_price_per_1k=None,
        )
    return list(unique.values())


def _pricing_is_free(pricing: dict[str, Any]) -> bool:
    """Classify only complete provider price vectors that are entirely zero."""
    if pricing.get("prompt") is None or pricing.get("completion") is None:
        return False
    try:
        values = [float(value) for value in pricing.values() if value is not None]
    except (TypeError, ValueError):
        return False
    if values:
        return all(value == 0.0 for value in values)
    return False


def _models_dev_cost_is_free(cost: object) -> bool:
    """Return whether every declared Models.dev monetary component is exactly zero."""
    if not isinstance(cost, dict) or not cost:
        return False
    monetary_values: list[object] = []

    def collect(value: object, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                collect(child_value, child_key)
        elif isinstance(value, list):
            for child_value in value:
                collect(child_value, key)
        elif key not in {"size"}:
            monetary_values.append(value)

    collect(cost)
    return bool(monetary_values) and all(
        _valid_price_component(value) and float(value) == 0.0 for value in monetary_values
    )


def _merge_models_dev_metadata(payload: Any, metadata: Any, provider: str) -> Any:
    """Join an availability catalog with Models.dev cost and modality evidence."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    provider_row = metadata.get(provider) if isinstance(metadata, dict) else None
    models = provider_row.get("models") if isinstance(provider_row, dict) else None
    if not isinstance(rows, list) or not isinstance(models, dict):
        return payload
    enriched: list[Any] = []
    for row in rows:
        model_id = row.get("id") if isinstance(row, dict) else None
        model = models.get(model_id) if isinstance(model_id, str) else None
        if not isinstance(row, dict) or not isinstance(model, dict):
            enriched.append(row)
            continue
        cost = model.get("cost")
        pricing: dict[str, str] = {}
        if isinstance(cost, dict):
            for source_key, target_key in (("input", "prompt"), ("output", "completion")):
                value = cost.get(source_key)
                if _valid_price_component(value):
                    pricing[target_key] = str(Decimal(str(value)) / Decimal(1_000_000))
        modalities = model.get("modalities") if isinstance(model.get("modalities"), dict) else {}
        enriched.append(
            {
                **row,
                "pricing": pricing,
                "architecture": {
                    "input_modalities": modalities.get("input"),
                    "output_modalities": modalities.get("output"),
                },
                "is_free": _models_dev_cost_is_free(cost),
            }
        )
    return {**payload, "data": enriched}


def _parse_openai_compatible(payload: Any, source: ProviderModelSource) -> list[DiscoveredModel]:
    rows = payload.get("data") if isinstance(payload, dict) else None
    discovered: list[DiscoveredModel] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        if type(model_id) is not str or not model_id:
            continue
        pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
        architecture = row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
        supported_parameters = (
            row.get("supported_parameters")
            if isinstance(row.get("supported_parameters"), list)
            else []
        )
        raw_inputs = architecture.get("input_modalities")
        raw_outputs = architecture.get("output_modalities")
        inputs = tuple(value for value in raw_inputs if isinstance(value, str)) if isinstance(raw_inputs, list) else ()
        outputs = tuple(value for value in raw_outputs if isinstance(value, str)) if isinstance(raw_outputs, list) else ()
        if (
            not outputs
            and not any(capability != "chat" for capability in source.capabilities)
            and not is_general_chat_agent_model_id(model_id)
        ):
            continue
        source_capabilities = tuple(
            capability
            for capability in source.capabilities
            if capability != "chat" or not outputs or "text" in outputs
        )
        capabilities = tuple(
            dict.fromkeys(
                _CAPABILITY_NAMES.get(value, value)
                for value in (
                    *source_capabilities,
                    *outputs,
                    *(
                        ("response_format",)
                        if "response_format" in supported_parameters
                        and (not outputs or "text" in outputs)
                        else ()
                    ),
                )
            )
        )
        prompt_price = _price_per_1k(pricing.get("prompt"))
        completion_price = _price_per_1k(pricing.get("completion"))
        discovered.append(
            DiscoveredModel(
                provider_name=source.provider_name,
                model_id=model_id,
                credential_name=source.credential_name,
                chat_base_url=source.chat_base_url,
                auth_scheme=source.auth_scheme,
                capabilities=capabilities,
                input_modalities=inputs,
                output_modalities=outputs,
                prompt_price_per_1k=prompt_price,
                completion_price_per_1k=completion_price,
                is_free=(
                    row["is_free"]
                    if isinstance(row.get("is_free"), bool)
                    else _pricing_is_free(pricing)
                ),
            )
        )
    return _deduplicate_discovered_models(discovered)


def _parse_bytez(payload: Any, source: ProviderModelSource) -> list[DiscoveredModel]:
    rows = payload.get("output") if isinstance(payload, dict) else None
    discovered: list[DiscoveredModel] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        model_id = row.get("modelId")
        if type(model_id) is not str or not model_id:
            continue
        declares_non_chat = any(
            capability not in {"chat", "text"}
            for capability in source.capabilities
        )
        if not declares_non_chat and not is_general_chat_agent_model_id(model_id):
            continue
        discovered.append(
            DiscoveredModel(
                provider_name=source.provider_name,
                model_id=model_id,
                credential_name=source.credential_name,
                chat_base_url=source.chat_base_url,
                auth_scheme=source.auth_scheme,
                capabilities=source.capabilities,
                # Bytez prices by GPU-second (meterPrice), not per-token; leaving
                # per-1k pricing unset is more honest than a misleading estimate.
            )
        )
    return _deduplicate_discovered_models(discovered)


def _openrouter_zdr_model_ids(*, timeout: float) -> set[str]:
    """Read public OpenRouter ZDR evidence for discovered provider models."""
    api_key = get_credential("OPENROUTER_API_KEY") or ""
    try:
        payload = _fetch_json(
            OPENROUTER_ZDR_ENDPOINTS_URL,
            api_key=api_key,
            timeout=timeout,
        )
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return set()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return set()
    return {
        row["model_id"].casefold()
        for row in rows or ()
        if isinstance(row, dict)
        and isinstance(row.get("model_id"), str)
        and row["model_id"].strip()
    }


def _apply_discovered_model_evidence(
    discovered: list[DiscoveredModel], zdr_model_ids: set[str]
) -> list[DiscoveredModel]:
    """Apply model-level ZDR evidence to matching rows from every provider.

    Providers may expose the same canonical model id as OpenRouter while using
    a different upstream endpoint. Exact canonical ids are the only portable
    identity; suffix matching would transfer privacy evidence to an unrelated
    model that merely shares a display name.
    """
    if not zdr_model_ids:
        return discovered
    exact_ids = {model_id.strip().casefold() for model_id in zdr_model_ids if model_id.strip()}

    def matches(model_id: str) -> bool:
        normalized = model_id.strip().casefold()
        return normalized in exact_ids

    return [
        replace(
            model,
            zdr_capable=not model.evidence_only and matches(model.model_id),
        )
        for model in discovered
    ]


def discover_provider_models(
    source: ProviderModelSource,
    *,
    timeout: float = DISCOVERY_TIMEOUT_SECONDS,
    models_dev_metadata: Any = _NOT_FETCHED,
) -> list[DiscoveredModel]:
    """Discover one provider's models, or ``[]`` if its credential is not registered.

    ``models_dev_metadata`` lets a caller that already fetched
    ``https://models.dev/api.json`` (e.g. :func:`discover_all_models`, once,
    for every source that wants it) hand the parsed payload in directly so
    this call does not repeat the fetch. Leaving it at the default sentinel
    preserves this function's existing lazy, per-call fetch-on-demand
    behavior for every other caller, tests included.
    """
    api_key = get_credential(source.credential_name)
    if not api_key:
        return []
    url = source.list_url
    if source.task_filter:
        url = f"{url}?task={source.task_filter}"
    try:
        payload = _fetch_json(url, api_key=api_key, auth_scheme=source.auth_scheme, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        # OSError covers ConnectionError/reset failures that are not URLError
        # subclasses, so a raw provider transport failure can never escape the
        # discovery boundary with provider text attached.
        raise ProviderDiscoveryError(source.provider_name, _provider_discovery_error_code(exc)) from None
    if source.models_dev_provider_id:
        if models_dev_metadata is _NOT_FETCHED:
            metadata = _fetch_models_dev_metadata(timeout=timeout)
        else:
            metadata = models_dev_metadata
        payload = _merge_models_dev_metadata(payload, metadata, source.models_dev_provider_id)
    if source.style == "bytez":
        discovered = _parse_bytez(payload, source)
    else:
        discovered = _parse_openai_compatible(payload, source)
    return [replace(model, evidence_only=source.evidence_only) for model in discovered]


def discover_all_models(
    sources: tuple[ProviderModelSource, ...] = PROVIDER_MODEL_SOURCES,
    *,
    timeout: float = DISCOVERY_TIMEOUT_SECONDS,
) -> tuple[list[DiscoveredModel], list[ProviderDiscoveryError]]:
    """Discover models across every provider with a registered credential.

    One provider's failure never blocks the others: errors are collected and
    returned alongside whatever models were successfully discovered.

    Up to four sources (``opencode_zen``, ``nvidia_nim``, ``nvidia_nim_sub``,
    ``openai``) each want the same Models.dev catalog. When any registered
    source declares ``models_dev_provider_id``, fetch it here exactly once
    (:func:`_fetch_models_dev_metadata`, with its own small bounded retry) and
    hand every source the identical parsed payload, instead of each source
    independently repeating the fetch inside :func:`discover_provider_models`.
    """
    discovered: list[DiscoveredModel] = []
    errors: list[ProviderDiscoveryError] = []
    models_dev_metadata: Any = _NOT_FETCHED
    if any(
        source.models_dev_provider_id and get_credential(source.credential_name)
        for source in sources
    ):
        models_dev_metadata = _fetch_models_dev_metadata(timeout=timeout)
    for source in sources:
        try:
            discovered.extend(
                discover_provider_models(
                    source,
                    timeout=timeout,
                    models_dev_metadata=models_dev_metadata,
                )
            )
        except ProviderDiscoveryError as exc:
            errors.append(exc)
    # The OpenRouter catalog is evidence-only; its public ZDR endpoint supplies
    # matching privacy evidence for discovered models from other providers. It
    # is never selected as an inference upstream here.
    return _apply_discovered_model_evidence(
        _deduplicate_discovered_models(discovered),
        _openrouter_zdr_model_ids(timeout=timeout),
    ), errors


def openrouter_paid_inference_available(
    *, timeout: float = DISCOVERY_TIMEOUT_SECONDS
) -> bool | None:
    """Return whether OpenRouter attests a strictly positive credit balance."""
    api_key = get_credential("OPENROUTER_API_KEY")
    if not api_key:
        return None
    try:
        payload = _fetch_json(
            _OPENROUTER_CREDITS_URL,
            api_key=api_key,
            timeout=timeout,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        total_credits = Decimal(str(data["total_credits"]))
        total_usage = Decimal(str(data["total_usage"]))
        if not total_credits.is_finite() or not total_usage.is_finite():
            return None
        return total_credits - total_usage > 0
    except (
        ArithmeticError,
        KeyError,
        TypeError,
        ValueError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ):
        return None


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    slug = _SLUG_RE.sub("_", value.lower()).strip("_")
    return slug or "model"


def agent_id_for(discovered: DiscoveredModel) -> str:
    """Two-or-more-word snake_case id, matching this repo's naming convention."""
    return f"{discovered.provider_name}_{_slug(discovered.model_id)}"


def is_routable_discovered_model(discovered: DiscoveredModel) -> bool:
    """Return whether a discovered row may become an ordinary chat agent.

    Explicit catalog metadata is authoritative when present. A provider may
    expose a media-only model with a generic identifier, so the model-name
    heuristic is only a fallback for rows with no capability or modality data.
    """
    return not discovered.evidence_only and is_general_chat_candidate(
        discovered.model_id,
        capabilities=discovered.capabilities,
        output_modalities=discovered.output_modalities,
    )


def agent_from_discovered(discovered: DiscoveredModel, *, priority: int = 0) -> ModelAgent:
    """Build a disabled capability agent or reject a chat-ineligible record."""
    if discovered.evidence_only:
        raise ValueError("evidence-only model cannot become a serving agent")
    if not any(
        capability not in {"chat", "response_format"}
        for capability in discovered.capabilities
    ) and not (
        is_general_chat_agent_model_id(discovered.model_id)
    ):
        raise ValueError("model is not eligible for a general chat agent")
    return ModelAgent(
        id=agent_id_for(discovered),
        model=discovered.model_id,
        base_url=discovered.chat_base_url,
        credential_key=discovered.credential_name,
        auth_scheme=discovered.auth_scheme,
        provider_name=discovered.provider_name,
        tags=(
            "discovered",
            *(("cost:free",) if discovered.is_free else ()),
            *(("privacy:zdr",) if discovered.zdr_capable else ()),
            *discovered.capabilities,
            *(f"capability:{value}" for value in discovered.capabilities),
            *(f"input:{value}" for value in discovered.input_modalities),
            *(f"output:{value}" for value in discovered.output_modalities),
        ),
        priority=priority,
        disabled=True,
    )


def free_discovered_models(discovered: list[DiscoveredModel]) -> list[DiscoveredModel]:
    """Return models whose provider metadata identifies zero-cost inference."""
    return [model for model in discovered if model.is_free]


def _currency_is_comparable(currency_code: object, default_currency: object) -> bool:
    """Return whether two ISO-style currency codes can be compared directly."""
    return (
        isinstance(currency_code, str)
        and isinstance(default_currency, str)
        and currency_code.strip().upper() == default_currency.strip().upper()
        and bool(currency_code.strip())
    )

def refresh_price_book(discovered: list[DiscoveredModel], price_book: "PriceBook") -> int:
    """Write complete, comparable provider pricing into the discovery price book.

    Both prompt and completion prices are required for the fixed 1K+1K ranking
    workload. Partial, conflicting, non-finite, negative, or cross-currency
    evidence remains unknown rather than acquiring an invented zero component.
    """
    from .cost_ledger import PriceEntry

    written = 0
    for model in _deduplicate_discovered_models(discovered):
        if not is_general_chat_agent_model_id(model.model_id):
            continue
        if not (
            _valid_price_component(model.prompt_price_per_1k)
            and _valid_price_component(model.completion_price_per_1k)
            and _currency_is_comparable(
                model.currency_code,
                price_book.default_currency,
            )
        ):
            continue
        price_book.set_price(
            PriceEntry(
                provider_name=model.provider_name,
                model_name=model.model_id,
                prompt_price_per_1k=float(model.prompt_price_per_1k),
                completion_price_per_1k=float(model.completion_price_per_1k),
                currency_code=model.currency_code.strip().upper(),
            )
        )
        written += 1
    return written


def _discovery_price_key(
    model: DiscoveredModel,
    price_book: "PriceBook",
) -> tuple[int, float, str, str]:
    """Rank comparable trustworthy prices first, then deterministic unknowns."""
    unknown = (1, 0.0, model.provider_name, model.model_id)
    try:
        entry = price_book.get_price(model.provider_name, model.model_id)
    except (TypeError, ValueError, OverflowError):
        return unknown
    if entry is None:
        if not (
            _valid_price_component(model.prompt_price_per_1k)
            and _valid_price_component(model.completion_price_per_1k)
            and _currency_is_comparable(model.currency_code, price_book.default_currency)
        ):
            return unknown
        return (
            0,
            float(model.prompt_price_per_1k) + float(model.completion_price_per_1k),
            model.provider_name,
            model.model_id,
        )
    if not (
        _valid_price_component(entry.prompt_price_per_1k)
        and _valid_price_component(entry.completion_price_per_1k)
        and _currency_is_comparable(
            entry.currency_code,
            price_book.default_currency,
        )
    ):
        return unknown
    try:
        cost, currency = price_book.compute_cost(
            model.provider_name,
            model.model_id,
            1000,
            1000,
        )
    except (TypeError, ValueError, OverflowError):
        return unknown
    if not (
        _valid_price_component(cost)
        and _currency_is_comparable(currency, price_book.default_currency)
    ):
        return unknown
    return (0, cost, model.provider_name, model.model_id)


def _provider_family(provider_name: str) -> str:
    """Collapse credentials that share one upstream provider outage domain."""
    if provider_name in {"nvidia_nim", "nvidia_nim_sub"}:
        return "nvidia_nim"
    return provider_name


def select_cheapest_discovered_agent(
    discovered: list[DiscoveredModel], price_book: "PriceBook"
) -> DiscoveredModel | None:
    """Pick the cheapest candidate with trustworthy price evidence.

    A candidate without a price row is unknown, not free. Known prices therefore
    sort first; when every candidate is unpriced, provider and model identifiers
    provide deterministic fallback ordering without inventing a monetary value.
    """
    eligible = [
        model
        for model in _deduplicate_discovered_models(discovered)
        if is_routable_discovered_model(model)
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda model: _discovery_price_key(model, price_book))


def select_top_n_cheapest_discovered_agents(
    discovered: list[DiscoveredModel], price_book: "PriceBook", limit: int
) -> list[DiscoveredModel]:
    """Return up to ``limit`` unique candidates, known-priced before unknown."""
    if limit <= 0:
        return []
    eligible = [
        model
        for model in _deduplicate_discovered_models(discovered)
        if is_routable_discovered_model(model)
    ]
    if not eligible:
        return []
    return sorted(
        eligible,
        key=lambda model: _discovery_price_key(model, price_book),
    )[:limit]


def select_bootstrap_discovered_agents(
    discovered: list[DiscoveredModel],
    price_book: "PriceBook",
    limit: int,
) -> list[DiscoveredModel]:
    """Build a deterministic, price-honest, provider-diverse initial pool.

    Candidates retain the known-price-first ordering above, but the first pass
    takes at most one model from each independent provider family. Remaining
    capacity is filled in the same deterministic cost order. NVIDIA NIM primary
    and sub credentials are one outage domain, so they participate in the second
    pass only after independently hosted providers have had a chance to enter.
    Duplicate serving identities never consume capacity twice.
    """
    if limit <= 0:
        return []
    eligible = [
        model
        for model in _deduplicate_discovered_models(discovered)
        if is_routable_discovered_model(model)
    ]
    if not eligible:
        return []

    ranked = sorted(
        eligible,
        key=lambda model: _discovery_price_key(model, price_book),
    )
    selected: list[DiscoveredModel] = []
    deferred: list[DiscoveredModel] = []
    provider_families: set[str] = set()

    for model in ranked:
        family = _provider_family(model.provider_name)
        if family in provider_families:
            deferred.append(model)
            continue
        provider_families.add(family)
        selected.append(model)
        if len(selected) == limit:
            return selected

    selected.extend(deferred[: limit - len(selected)])
    return selected
