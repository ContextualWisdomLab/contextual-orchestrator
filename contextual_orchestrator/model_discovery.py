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
from concurrent.futures import ThreadPoolExecutor
import json
import math
import re
import ssl
import time
import urllib.error
import urllib.request
import certifi
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, Mapping
from urllib.parse import quote, urlsplit, urlunsplit

from .chat_capability import is_general_chat_agent_model_id, is_general_chat_candidate
from .credentials import get_credential
from .orchestrator import ModelAgent, ModelClient, is_transient_error

if TYPE_CHECKING:
    from .cost_ledger import PriceBook

DISCOVERY_TIMEOUT_SECONDS = 15.0
# One bounded retry for a provider's primary model-list fetch, reusing the same
# transient-vs-terminal classification completion calls already trust
# (is_transient_error). A short, fixed delay and a shortened retry timeout keep
# the added worst case small and predictable for CI callers with their own
# overall time budget (see ContextualWisdomLab/.github's review sidecar).
# Non-transient failures (auth/config errors, malformed responses) are never
# retried — a retry cannot fix those and would only waste the time budget.
_DISCOVERY_RETRY_TIMEOUT_SECONDS = 5.0
_DISCOVERY_RETRY_DELAY_SECONDS = 0.5
# Some discovery endpoints (verified live: models.dev returns Cloudflare HTTP
# 403 error 1010) reject urllib's default "Python-urllib/X.Y" user agent as a
# bot signature. A stable, identifying user agent is not a credential and is
# safe to send on every request, authenticated or not.
_HTTP_USER_AGENT = "contextual-orchestrator/0.2.0 (+https://github.com/ContextualWisdomLab/contextual-orchestrator)"
_CAPABILITY_NAMES = {"embeddings": "embedding"}
_MODELS_DEV_URL = "https://models.dev/api.json"
_OPENROUTER_ZDR_ENDPOINTS_URL = "https://openrouter.ai/api/v1/endpoints/zdr"
_OPENROUTER_PROVIDER_POLICIES_URL = "https://openrouter.ai/api/frontend/v1/all-providers"
CONFIGURED_GATEWAY_CREDENTIAL_NAME = "LLM_GATEWAY_API_KEY"
MAX_DISCOVERY_RESPONSE_BYTES = 8 * 1024 * 1024
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
    privacy_policy_urls: tuple[str, ...] = ()
    bootstrap_required: bool = True
    evidence_only: bool = False
    models_dev_provider_id: str | None = None


def configured_gateway_source(
    environ: Mapping[str, str],
) -> ProviderModelSource | None:
    """Build one allowlisted OpenAI-compatible gateway source at bootstrap.

    The URL is non-secret bootstrap transport. The API key is referenced only
    by its KV credential name; callers may promote the environment value into
    the credential registry before runtime discovery starts.
    """
    values = {
        value.strip().rstrip("/")
        for name in ("LLM_GATEWAY_API_URL", "LLM_GATEWAY_URL")
        if isinstance((value := environ.get(name)), str) and value.strip()
    }
    if not values:
        return None
    if len(values) != 1:
        raise ValueError("LLM gateway URL settings must identify the same endpoint")
    raw_url = values.pop()
    parsed = urlsplit(raw_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("LLM gateway URL must be a credential-free HTTPS base URL")
    allowed_hosts = {
        host.strip().casefold()
        for host in environ.get(
            "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS", ""
        ).split(",")
        if host.strip()
    }
    if parsed.hostname.casefold() not in allowed_hosts:
        raise ValueError("LLM gateway host must be present in the provider allowlist")
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1"):
        path += "/v1"
    base_url = urlunsplit(("https", parsed.netloc, path, "", ""))
    return ProviderModelSource(
        provider_name="configured_gateway",
        credential_name=CONFIGURED_GATEWAY_CREDENTIAL_NAME,
        list_url=f"{base_url}/models",
        chat_base_url=base_url,
        capabilities=("chat",),
    )


# NVIDIA NIM is listed twice under two KV credential names (primary + sub) so both
# keys participate in upstream load balancing without a second provider identity.
PROVIDER_MODEL_SOURCES: tuple[ProviderModelSource, ...] = (
    ProviderModelSource(
        provider_name="openai",
        credential_name="OPENAI_API_KEY",
        list_url="https://api.openai.com/v1/models",
        chat_base_url="https://api.openai.com/v1",
        privacy_policy_urls=("https://platform.openai.com/docs/guides/your-data",),
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

@dataclass(frozen=True)
class ModelUnitPrice:
    """A provider-reported price whose billing unit is not a text token."""

    dimension: Literal[
        "input_cost_per_image", "input_cost_per_pixel", "input_cost_per_second",
        "input_cost_per_audio_per_second", "input_cost_per_video_per_second",
        "output_cost_per_image", "output_cost_per_pixel", "output_cost_per_second",
        "output_cost_per_second_480p", "output_cost_per_second_1080p",
        "output_cost_per_second_4k", "output_cost_per_audio_per_second",
        "output_cost_per_video_per_second",
    ]
    price: float
    currency_code: str = "USD"


UNIT_PRICE_DIMENSIONS = frozenset({
    "input_cost_per_image", "input_cost_per_pixel", "input_cost_per_second",
    "input_cost_per_audio_per_second", "input_cost_per_video_per_second",
    "output_cost_per_image", "output_cost_per_pixel", "output_cost_per_second",
    "output_cost_per_second_480p", "output_cost_per_second_1080p",
    "output_cost_per_second_4k", "output_cost_per_audio_per_second",
    "output_cost_per_video_per_second",
})


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
    unit_prices: tuple[ModelUnitPrice, ...] = ()
    is_free: bool = False
    supports_zero_data_retention: bool | None = None
    supports_no_training: bool | None = None
    supports_no_prompt_retention: bool | None = None
    privacy_policy_urls: tuple[str, ...] = ()
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
    try:
        response = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - fixed provider inventory  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise
        context = ssl.create_default_context(cafile=certifi.where())
        response = urllib.request.urlopen(  # noqa: S310 - fixed provider inventory  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            request, timeout=timeout, context=context
        )
    with response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_configured_gateway_json(
    url: str,
    *,
    api_key: str,
    auth_scheme: str,
    timeout: float,
    ca_bundle: str | None = None,
) -> Any:
    """Fetch an operator URL through the gateway's pinned hardened transport."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("configured gateway discovery URL is not a safe HTTPS URL")
    origin = urlunsplit(("https", parsed.netloc, "", "", ""))
    client = ModelClient(
        ca_bundle=ca_bundle,
        timeout=max(1, math.ceil(timeout)),
        allowed_provider_hosts={parsed.hostname},
    )
    agent = ModelAgent(
        "configured_gateway_discovery",
        "configured-gateway-catalog",
        base_url=origin,
        credential_key=CONFIGURED_GATEWAY_CREDENTIAL_NAME,
    )
    destination = client._validate_provider(agent)
    headers = {"authorization": f"{auth_scheme} {api_key}"} if api_key else {}
    request = urllib.request.Request(url, headers=headers, method="GET")
    with client._open_provider(request, destination, timeout=timeout) as response:
        raw = response.read(MAX_DISCOVERY_RESPONSE_BYTES + 1)
    if len(raw) > MAX_DISCOVERY_RESPONSE_BYTES:
        raise ValueError("configured gateway discovery response exceeds the size limit")
    return json.loads(raw.decode("utf-8"))


class _TrustedDiscoveryRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Allow authenticated discovery redirects only within one trusted HTTPS host."""

    def __init__(self, trusted_host: str) -> None:
        self._trusted_host = trusted_host.casefold()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Follow a redirect only when it stays on the trusted HTTPS host."""
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.casefold() != self._trusted_host:
            raise urllib.error.HTTPError(
                newurl,
                code,
                "unsafe redirect during authenticated model discovery",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_json_same_host_https(
    url: str, *, api_key: str = "", auth_scheme: str = "Bearer", timeout: float
) -> Any:
    """Fetch JSON while rejecting redirects outside the original trusted HTTPS host."""
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https model discovery URL: {url!r}")
    parsed = urlsplit(url)
    if not parsed.hostname:
        raise ValueError(f"refusing discovery URL without hostname: {url!r}")
    headers = {"authorization": f"{auth_scheme} {api_key}"} if api_key else {}
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(
        _TrustedDiscoveryRedirectHandler(parsed.hostname)
    )
    try:
        response = opener.open(request, timeout=timeout)  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise TimeoutError(str(exc.reason)) from exc
        raise
    with response:
        raw = response.read(MAX_DISCOVERY_RESPONSE_BYTES + 1)
    if len(raw) > MAX_DISCOVERY_RESPONSE_BYTES:
        raise ValueError("model discovery response exceeds maximum size")
    return json.loads(raw.decode("utf-8"))


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
            unit_prices=(),
            is_free=False,
            supports_zero_data_retention=None,
            supports_no_training=None,
            supports_no_prompt_retention=None,
            zdr_capable=False,
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


def _unit_prices_are_free(
    raw_unit_prices: object,
    *,
    provider_declares_free: bool,
    inputs: tuple[str, ...],
    outputs: tuple[str, ...],
) -> bool:
    """Return whether a non-token price vector is complete and entirely zero."""
    non_text_modalities = {
        modality for modality in (*inputs, *outputs) if modality != "text"
    }
    if not isinstance(raw_unit_prices, dict):
        return provider_declares_free or not non_text_modalities
    unknown_dimensions = {
        key for key in raw_unit_prices if isinstance(key, str) and key not in UNIT_PRICE_DIMENSIONS
    }
    if unknown_dimensions:
        return False
    declared: dict[str, float] = {}
    for key in UNIT_PRICE_DIMENSIONS:
        if key not in raw_unit_prices:
            continue
        value = raw_unit_prices[key]
        if not _valid_price_component(value):
            return False
        declared[key] = float(value)
    if not declared:
        return provider_declares_free or not non_text_modalities
    return all(value == 0.0 for value in declared.values())


def _row_is_free(
    row: Mapping[str, Any],
    *,
    pricing: dict[str, Any],
    inputs: tuple[str, ...],
    outputs: tuple[str, ...],
) -> bool:
    """Classify only rows whose token and non-token prices are all known zero."""
    raw_unit_prices = row.get("unit_pricing")
    provider_declares_free = isinstance(row.get("is_free"), bool) and row["is_free"]
    if isinstance(row.get("is_free"), bool) and row["is_free"] is False:
        return False
    if not _pricing_is_free(pricing):
        return False
    return _unit_prices_are_free(
        raw_unit_prices,
        provider_declares_free=provider_declares_free,
        inputs=inputs,
        outputs=outputs,
    )


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


def _merge_configured_gateway_metadata(payload: Any, metadata: Any) -> Any:
    """Join safe LiteLLM model-info fields into the OpenAI model listing.

    A logical model may have several upstream deployments. Pricing is retained
    only when every deployment reports the same complete token-price pair;
    conflicts remain unknown instead of manufacturing a routing preference.
    """
    rows = payload.get("data") if isinstance(payload, dict) else None
    details = metadata.get("data") if isinstance(metadata, dict) else None
    if not isinstance(rows, list) or not isinstance(details, list):
        return payload
    by_name: dict[str, list[dict[str, Any]]] = {}
    for detail in details:
        if not isinstance(detail, dict):
            continue
        model_name = detail.get("model_name")
        names = set()
        if isinstance(model_name, str):
            names.add(model_name)
        info = detail.get("model_info")
        if isinstance(info, dict):
            base_model = info.get("base_model")
            if isinstance(base_model, str):
                names.add(base_model)
            if isinstance(info.get("id"), str):
                names.add(info["id"])
        for name in names:
            by_name.setdefault(name, []).append(detail)
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        # The generic listing cannot prove that one price/capability applies to
        # every deployment behind a logical id. Only reviewed full consensus
        # below may restore these fields.
        row.pop("pricing", None)
        row.pop("architecture", None)
        row.pop("unit_pricing", None)
        for key in (
            "supports_zero_data_retention",
            "supports_no_training",
            "supports_no_prompt_retention",
            "privacy_policy_urls",
        ):
            row.pop(key, None)
        model_details = by_name.get(row["id"], [])
        deployment_outputs: list[tuple[str, ...]] = []
        deployment_inputs: list[tuple[str, ...]] = []
        prices: set[tuple[object, object]] = set()
        pricing_complete = bool(model_details)
        unit_price_maps: list[tuple[tuple[str, object], ...]] = []
        privacy_values = {
            key: []
            for key in (
                "supports_zero_data_retention",
                "supports_no_training",
                "supports_no_prompt_retention",
            )
        }
        policy_urls: set[str] = set()
        for detail in model_details:
            info = detail.get("model_info") if isinstance(detail.get("model_info"), dict) else {}
            params = detail.get("litellm_params") if isinstance(detail.get("litellm_params"), dict) else {}
            mode = info.get("mode")
            normalized_mode = mode.casefold() if isinstance(mode, str) else ""
            mode_modalities = {
                "chat": (("text",), ("text",)),
                "responses": (("text",), ("text", "responses")),
                "completion": (("text",), ("text", "completion")),
                "embedding": (("text",), ("embedding",)),
                "image_generation": (("text",), ("image",)),
                "image_edit": (("text", "image"), ("image",)),
                "audio_speech": (("text",), ("speech",)),
                "audio_transcription": (("audio",), ("transcription",)),
                "video_generation": (("text",), ("video",)),
                "rerank": (("text",), ("rerank",)),
                "ocr": (("image",), ("text",)),
                "realtime": ((), ("realtime",)),
                "guardrail": ((), ("guardrail",)),
                "moderation": ((), ("moderation",)),
                "search": ((), ("search",)),
                "vector_store": ((), ("vector_store",)),
            }
            fallback_inputs, fallback_outputs = mode_modalities.get(
                normalized_mode, ((), ())
            )
            declared_inputs = info.get(
                "supported_modalities", info.get("supported_input_modalities")
            )
            declared_outputs = info.get("supported_output_modalities")
            inputs = (
                tuple(value for value in declared_inputs if isinstance(value, str))
                if isinstance(declared_inputs, list)
                else fallback_inputs
            )
            outputs = (
                tuple(value for value in declared_outputs if isinstance(value, str))
                if isinstance(declared_outputs, list)
                else fallback_outputs
            )
            deployment_outputs.append(outputs)
            if info.get("supports_vision") is True and "image" not in inputs:
                inputs = (*inputs, "image")
            deployment_inputs.append(inputs)
            prompt = info.get("input_cost_per_token", params.get("input_cost_per_token"))
            completion = info.get(
                "output_cost_per_token", params.get("output_cost_per_token")
            )
            if _valid_price_component(prompt) and _valid_price_component(completion):
                prices.add((prompt, completion))
            else:
                pricing_complete = False
            unit_prices: list[tuple[str, object]] = []
            for key in sorted(UNIT_PRICE_DIMENSIONS):
                value = info.get(key, params.get(key))
                if _valid_price_component(value):
                    unit_prices.append((key, value))
            unit_price_maps.append(tuple(unit_prices))
            for key, values in privacy_values.items():
                values.append(info.get(key, params.get(key)))
            for key in ("privacy_policy_url", "terms_of_service_url"):
                value = info.get(key, params.get(key))
                if (
                    isinstance(value, str)
                    and urlsplit(value).scheme == "https"
                    and urlsplit(value).hostname
                ):
                    policy_urls.add(value)
        capability_complete = bool(model_details) and all(deployment_outputs)
        capability_consensus = (
            capability_complete
            and len(set(deployment_outputs)) == 1
            and len(set(deployment_inputs)) == 1
        )
        if capability_consensus:
            row["architecture"] = {
                "input_modalities": list(deployment_inputs[0]),
                "output_modalities": list(deployment_outputs[0]),
            }
        if pricing_complete and len(prices) == 1:
            prompt, completion = prices.pop()
            if prompt is not None and completion is not None:
                row["pricing"] = {"prompt": prompt, "completion": completion}
        if unit_price_maps and unit_price_maps[0] and len(set(unit_price_maps)) == 1:
            row["unit_pricing"] = dict(unit_price_maps[0])
        for key, values in privacy_values.items():
            parsed_values = []
            for v in values:
                if isinstance(v, bool):
                    parsed_values.append(v)
                elif isinstance(v, str):
                    normalized = v.strip().casefold()
                    parsed_values.append(
                        True
                        if normalized == "true"
                        else False
                        if normalized == "false"
                        else None
                    )
                else:
                    parsed_values.append(None)
            
            if parsed_values and all(isinstance(value, bool) for value in parsed_values) and len(set(parsed_values)) == 1:
                row[key] = parsed_values[0]
        if policy_urls:
            row["privacy_policy_urls"] = sorted(policy_urls)
    return payload


def _merge_openrouter_zdr_metadata(payload: Any, metadata: Any) -> Any:
    """Mark models with at least one endpoint in OpenRouter's authoritative ZDR list."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    endpoints = metadata.get("data") if isinstance(metadata, dict) else None
    if not isinstance(rows, list) or not isinstance(endpoints, list):
        return payload
    zdr_models = {
        endpoint["model_id"]
        for endpoint in endpoints
        if isinstance(endpoint, dict) and isinstance(endpoint.get("model_id"), str)
    }
    if not zdr_models:
        return payload
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            row["supports_zero_data_retention"] = row["id"] in zdr_models
    return payload


def _merge_openrouter_provider_privacy(
    payload: Any, providers: Any, endpoints_by_model: Mapping[str, Any]
) -> Any:
    """Join provider-declared training, retention, and policy evidence for free models."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    provider_rows = providers.get("data") if isinstance(providers, dict) else None
    if not isinstance(rows, list) or not isinstance(provider_rows, list):
        return payload
    policies = {
        provider["slug"]: provider["dataPolicy"]
        for provider in provider_rows
        if isinstance(provider, dict)
        and isinstance(provider.get("slug"), str)
        and isinstance(provider.get("dataPolicy"), dict)
    }
    for row in rows:
        model_id = row.get("id") if isinstance(row, dict) else None
        details = endpoints_by_model.get(model_id) if isinstance(model_id, str) else None
        endpoints = details.get("endpoints") if isinstance(details, dict) else None
        if not isinstance(endpoints, list) or not endpoints:
            continue
        endpoint_policies = [
            policies.get(endpoint.get("tag"))
            for endpoint in endpoints
            if isinstance(endpoint, dict)
        ]
        complete = len(endpoint_policies) == len(endpoints) and all(
            isinstance(policy, dict) for policy in endpoint_policies
        )
        known = [policy for policy in endpoint_policies if isinstance(policy, dict)]
        for source_key, target_key in (
            ("training", "supports_no_training"),
            ("retainsPrompts", "supports_no_prompt_retention"),
        ):
            values = [policy.get(source_key) for policy in known]
            if complete and values and all(isinstance(value, bool) for value in values):
                if all(value is False for value in values):
                    row[target_key] = True
                elif all(value is True for value in values):
                    row[target_key] = False
        urls = {
            value
            for policy in known
            for key in ("privacyPolicyURL", "termsOfServiceURL")
            if isinstance((value := policy.get(key)), str)
            and urlsplit(value).scheme == "https"
            and urlsplit(value).hostname
        }
        if urls:
            row["privacy_policy_urls"] = sorted(urls)
    return payload


def _openrouter_free_model_endpoints(
    payload: Any, *, api_key: str, timeout: float
) -> dict[str, Any]:
    """Fetch endpoint/provider mappings only for explicitly zero-price models."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    model_ids = [
        row["id"]
        for row in rows or ()
        if isinstance(row, dict)
        and isinstance(row.get("id"), str)
        and isinstance(row.get("pricing"), dict)
        and _pricing_is_free(row.get("pricing"))
    ]

    def fetch(model_id: str) -> tuple[str, Any]:
        author, separator, slug = model_id.partition("/")
        if not separator or not author or not slug:
            return model_id, None
        try:
            return model_id, _fetch_json(
                f"https://openrouter.ai/api/v1/models/{quote(author, safe='')}/{quote(slug, safe=':')}/endpoints",
                api_key=api_key,
                timeout=timeout,
            ).get("data")
        except (AttributeError, urllib.error.URLError, TimeoutError, ValueError, OSError):
            return model_id, None

    with ThreadPoolExecutor(max_workers=min(8, len(model_ids) or 1)) as executor:
        return dict(executor.map(fetch, model_ids))


def _privacy_policy_urls(
    source: ProviderModelSource, row: Mapping[str, Any]
) -> tuple[str, ...]:
    """Return unique HTTPS privacy evidence from the provider and model row."""
    raw = row.get("privacy_policy_urls")
    values = (*source.privacy_policy_urls, *(raw if isinstance(raw, (list, tuple)) else ()))
    return tuple(sorted({
        value
        for value in values
        if isinstance(value, str)
        and urlsplit(value).scheme == "https"
        and urlsplit(value).hostname
    }))


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
        # A generic OpenAI-compatible listing often carries no modality or
        # capability metadata for its chat deployments (e.g. a LiteLLM proxy
        # whose /model/info rows are incomplete or heterogeneous). Recover the
        # ordinary chat capability for metadata-free or explicit text-output
        # rows, but do not override explicit non-text modality evidence with a
        # positive chat claim inferred only from the model name.
        if (
            is_general_chat_agent_model_id(model_id)
            and "chat" not in capabilities
            and (not outputs or "text" in outputs)
        ):
            capabilities = ("chat", *capabilities)
        prompt_price = _price_per_1k(pricing.get("prompt"))
        completion_price = _price_per_1k(pricing.get("completion"))
        raw_unit_prices = row.get("unit_pricing")
        unit_prices = tuple(
            ModelUnitPrice(dimension=key, price=float(value))
            for key, value in sorted(
                raw_unit_prices.items() if isinstance(raw_unit_prices, dict) else ()
            )
            if key in UNIT_PRICE_DIMENSIONS
            and _valid_price_component(value)
        )
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
                unit_prices=unit_prices,
                is_free=_row_is_free(
                    row,
                    pricing=pricing,
                    inputs=inputs,
                    outputs=outputs,
                ),
                supports_zero_data_retention=(
                    row["supports_zero_data_retention"]
                    if isinstance(row.get("supports_zero_data_retention"), bool)
                    else None
                ),
                supports_no_training=(
                    row["supports_no_training"]
                    if isinstance(row.get("supports_no_training"), bool)
                    else None
                ),
                supports_no_prompt_retention=(
                    row["supports_no_prompt_retention"]
                    if isinstance(row.get("supports_no_prompt_retention"), bool)
                    else None
                ),
                privacy_policy_urls=_privacy_policy_urls(source, row),
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
                privacy_policy_urls=_privacy_policy_urls(source, row),
                # Bytez prices by GPU-second (meterPrice), not per-token; leaving
                # per-1k pricing unset is more honest than a misleading estimate.
            )
        )
    return _deduplicate_discovered_models(discovered)


def _openrouter_zdr_model_ids(*, timeout: float) -> set[str]:
    """Read public OpenRouter ZDR evidence for discovered provider models."""
    api_key = get_credential("OPENROUTER_API_KEY") or ""
    try:
        payload = _fetch_json_same_host_https(
            _OPENROUTER_ZDR_ENDPOINTS_URL,
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
    ca_bundle: str | None = None,
    models_dev_metadata: Any = _NOT_FETCHED,
) -> list[DiscoveredModel]:
    """Discover one provider's models, or ``[]`` if its credential is not registered.

    ``models_dev_metadata`` lets a caller that already fetched
    ``https://models.dev/api.json`` (e.g. :func:`discover_all_models`, once,
    for every source that wants it) hand the parsed payload in directly so
    this call does not repeat the fetch. Leaving it at the default sentinel
    preserves this function's existing lazy, per-call fetch-on-demand
    behavior for every other caller, tests included.

    The primary model-list fetch gets one bounded retry (short fixed delay,
    shortened timeout) when the failure is transient (5xx/timeout/connection
    reset, per :func:`~contextual_orchestrator.orchestrator.is_transient_error`)
    — a single provider's momentary blip no longer has to zero out that
    provider's entire contribution for this discovery pass. A non-transient
    failure (bad credential, malformed response) is never retried.
    """
    api_key = get_credential(source.credential_name)
    if not api_key:
        return []
    url = source.list_url
    if source.task_filter:
        url = f"{url}?task={source.task_filter}"
    fetch = (
        _fetch_configured_gateway_json
        if source.provider_name == "configured_gateway"
        else _fetch_json
    )
    fetch_kwargs = {
        "api_key": api_key,
        "auth_scheme": source.auth_scheme,
        **({"ca_bundle": ca_bundle} if source.provider_name == "configured_gateway" else {}),
    }
    attempt_timeouts = (timeout, min(timeout, _DISCOVERY_RETRY_TIMEOUT_SECONDS))
    payload: Any = None
    last_exc: Exception | None = None
    for attempt_index, attempt_timeout in enumerate(attempt_timeouts):
        try:
            payload = fetch(url, timeout=attempt_timeout, **fetch_kwargs)
            last_exc = None
            break
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            # OSError covers ConnectionError/reset failures that are not URLError
            # subclasses, so a raw provider transport failure can never escape the
            # discovery boundary with provider text attached.
            last_exc = exc
            is_last_attempt = attempt_index == len(attempt_timeouts) - 1
            if is_last_attempt or not is_transient_error(exc):
                break
            time.sleep(_DISCOVERY_RETRY_DELAY_SECONDS)
    if last_exc is not None:
        raise ProviderDiscoveryError(source.provider_name, _provider_discovery_error_code(last_exc)) from None
    if source.models_dev_provider_id:
        if models_dev_metadata is _NOT_FETCHED:
            try:
                metadata = _fetch_json(_MODELS_DEV_URL, timeout=timeout)
            except (urllib.error.URLError, TimeoutError, ValueError, OSError):
                metadata = None
        else:
            metadata = models_dev_metadata
        payload = _merge_models_dev_metadata(payload, metadata, source.models_dev_provider_id)
    elif source.provider_name == "openrouter":
        try:
            metadata = _fetch_json(_OPENROUTER_ZDR_ENDPOINTS_URL, api_key=api_key, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            metadata = None
        payload = _merge_openrouter_zdr_metadata(payload, metadata)
        try:
            policies = _fetch_json(_OPENROUTER_PROVIDER_POLICIES_URL, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            policies = None
        provider_rows = policies.get("data") if isinstance(policies, dict) else None
        endpoints_by_model = (
            _openrouter_free_model_endpoints(payload, api_key=api_key, timeout=timeout)
            if isinstance(provider_rows, list)
            else {}
        )
        payload = _merge_openrouter_provider_privacy(
            payload,
            policies,
            endpoints_by_model,
        )
    elif source.provider_name == "configured_gateway":
        try:
            metadata = _fetch_configured_gateway_json(
                f"{source.chat_base_url}/model/info",
                api_key=api_key,
                auth_scheme=source.auth_scheme,
                timeout=timeout,
                ca_bundle=ca_bundle,
            )
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            metadata = None
        payload = _merge_configured_gateway_metadata(payload, metadata)
    if source.style == "bytez":
        discovered = _parse_bytez(payload, source)
    else:
        discovered = _parse_openai_compatible(payload, source)
    return [replace(model, evidence_only=source.evidence_only) for model in discovered]


def discover_all_models(
    sources: tuple[ProviderModelSource, ...] = PROVIDER_MODEL_SOURCES,
    *,
    timeout: float = DISCOVERY_TIMEOUT_SECONDS,
    ca_bundle: str | None = None,
) -> tuple[list[DiscoveredModel], list[ProviderDiscoveryError]]:
    """Discover models across every provider with a registered credential.

    One provider's failure never blocks the others: errors are collected and
    returned alongside whatever models were successfully discovered.

    Up to four sources (``opencode_zen``, ``nvidia_nim``, ``nvidia_nim_sub``,
    ``openai``) each want the same Models.dev catalog. When any registered
    source declares ``models_dev_provider_id``, fetch it here exactly once and
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
        try:
            models_dev_metadata = _fetch_json(_MODELS_DEV_URL, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            models_dev_metadata = None
    for source in sources:
        try:
            discovered.extend(
                discover_provider_models(
                    source,
                    timeout=timeout,
                    ca_bundle=ca_bundle,
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


def privacy_tags_for_discovered(discovered: DiscoveredModel) -> tuple[str, ...]:
    """Translate only explicit provider privacy evidence into agent tags."""
    return (
        *(("privacy:zdr",) if (discovered.supports_zero_data_retention is True or discovered.zdr_capable) else ()),
        *(("privacy:no_zdr",) if discovered.supports_zero_data_retention is False else ()),
        *(("privacy:no_training",) if discovered.supports_no_training is True else ()),
        *(("privacy:training_only",) if discovered.supports_no_training is False else ()),
        *(("privacy:no_retention",) if discovered.supports_no_prompt_retention is True else ()),
        *(("privacy:retention_only",) if discovered.supports_no_prompt_retention is False else ()),
    )


def is_discovered_chat_candidate(discovered: DiscoveredModel) -> bool:
    """Return whether a discovered row is chat-compatible before serving policy.

    Provider-declared capabilities/modalities remain authoritative when
    present. The model-id heuristic is only the fallback for bare
    OpenAI-compatible listings that omit structured capability metadata.
    """
    return is_general_chat_candidate(
        discovered.model_id,
        capabilities=discovered.capabilities,
        output_modalities=discovered.output_modalities,
    )


def is_routable_discovered_model(discovered: DiscoveredModel) -> bool:
    """Return whether a discovered row may become an ordinary chat agent.

    Explicit catalog metadata is authoritative when present. A provider may
    expose a media-only model with a generic identifier, so the model-name
    heuristic is only a fallback for rows with no capability or modality data.
    """
    return not discovered.evidence_only and is_discovered_chat_candidate(
        discovered
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
            *privacy_tags_for_discovered(discovered),
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
        if not is_discovered_chat_candidate(model):
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
