"""Provider model-list discovery: turns registered KV credentials into agent candidates.

Queries each configured provider's model-list endpoint over its OpenAI-compatible
(or provider-specific) discovery API and returns :class:`DiscoveredModel` rows that
callers turn into :class:`~contextual_orchestrator.orchestrator.ModelAgent` entries
and/or :class:`~contextual_orchestrator.cost_ledger.PriceBook` rows.

Credentials are never fabricated: a provider resolves through :func:`get_credential`
(the KV registry), and a provider with nothing registered is silently skipped so
registering a subset of the five supported keys still works. Stdlib only
(``urllib.request``), matching this repo's dependency-free transport convention.
"""

from __future__ import annotations

from decimal import Decimal
import json
import math
import re
import ssl
import urllib.error
import urllib.request
import certifi
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from .chat_capability import is_general_chat_agent_model_id
from .credentials import get_credential
from .orchestrator import ModelAgent, ModelClient

if TYPE_CHECKING:
    from .cost_ledger import PriceBook

DISCOVERY_TIMEOUT_SECONDS = 15.0
_CAPABILITY_NAMES = {"embeddings": "embedding"}
_MODELS_DEV_URL = "https://models.dev/api.json"
_MODELS_DEV_OPENCODE_PROVIDER = "opencode"
_OPENROUTER_ZDR_ENDPOINTS_URL = "https://openrouter.ai/api/v1/endpoints/zdr"
CONFIGURED_GATEWAY_CREDENTIAL_NAME = "LLM_GATEWAY_API_KEY"
MAX_DISCOVERY_RESPONSE_BYTES = 8 * 1024 * 1024


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
    ),
    ProviderModelSource(
        provider_name="openrouter",
        credential_name="OPENROUTER_API_KEY",
        list_url="https://openrouter.ai/api/v1/models?output_modalities=all",
        chat_base_url="https://openrouter.ai/api/v1",
        capabilities=("chat",),
    ),
    ProviderModelSource(
        provider_name="opencode_zen",
        credential_name="OPENCODE_ZEN_API_KEY",
        list_url="https://opencode.ai/zen/v1/models",
        chat_base_url="https://opencode.ai/zen/v1",
        capabilities=("chat",),
    ),
    ProviderModelSource(
        provider_name="nvidia_nim",
        credential_name="NVIDIA_NIM_API_KEY",
        list_url="https://integrate.api.nvidia.com/v1/models",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        capabilities=("chat",),
    ),
    ProviderModelSource(
        provider_name="nvidia_nim_sub",
        credential_name="NVIDIA_NIM_API_KEY_SUB",
        list_url="https://integrate.api.nvidia.com/v1/models",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        capabilities=("chat",),
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
    supports_zero_data_retention: bool | None = None


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
    headers = {"authorization": f"{auth_scheme} {api_key}"} if api_key else {}
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
        timeout=max(1, int(math.ceil(timeout))),
        ca_bundle=certifi.where(),
        allowed_provider_hosts={parsed.hostname},
    )
    agent = ModelAgent(
        "configured_gateway_discovery",
        "configured-gateway-catalog",
        base_url=origin,
    )
    destination = client._validate_provider(agent)
    headers = {"authorization": f"{auth_scheme} {api_key}"} if api_key else {}
    request = urllib.request.Request(url, headers=headers, method="GET")
    with client._open_provider(request, destination, timeout=timeout) as response:
        raw = response.read(MAX_DISCOVERY_RESPONSE_BYTES + 1)
    if len(raw) > MAX_DISCOVERY_RESPONSE_BYTES:
        raise ValueError("configured gateway discovery response exceeds the size limit")
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
        if not isinstance(detail, dict) or not isinstance(detail.get("model_name"), str):
            continue
        by_name.setdefault(detail["model_name"], []).append(detail)
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        # The generic listing cannot prove that one price/capability applies to
        # every deployment behind a logical id. Only reviewed full consensus
        # below may restore these fields.
        row.pop("pricing", None)
        row.pop("architecture", None)
        model_details = by_name.get(row["id"], [])
        deployment_outputs: list[tuple[str, ...]] = []
        deployment_inputs: list[tuple[str, ...]] = []
        prices: set[tuple[object, object]] = set()
        pricing_complete = bool(model_details)
        for detail in model_details:
            info = detail.get("model_info") if isinstance(detail.get("model_info"), dict) else {}
            params = detail.get("litellm_params") if isinstance(detail.get("litellm_params"), dict) else {}
            mode = info.get("mode")
            normalized_mode = mode.casefold() if isinstance(mode, str) else ""
            outputs = tuple(
                capability
                for capability, matching_modes in (
                    ("text", {"chat", "responses", "completion"}),
                    ("embedding", {"embedding"}),
                )
                if normalized_mode in matching_modes
            )
            deployment_outputs.append(outputs)
            deployment_inputs.append(
                ("text", "image") if info.get("supports_vision") is True else ("text",)
            )
            prompt = info.get("input_cost_per_token", params.get("input_cost_per_token"))
            completion = info.get(
                "output_cost_per_token", params.get("output_cost_per_token")
            )
            if _valid_price_component(prompt) and _valid_price_component(completion):
                prices.add((prompt, completion))
            else:
                pricing_complete = False
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
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            row["supports_zero_data_retention"] = row["id"] in zdr_models
    return payload


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
                for value in (*source_capabilities, *outputs)
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
                supports_zero_data_retention=(
                    row["supports_zero_data_retention"]
                    if isinstance(row.get("supports_zero_data_retention"), bool)
                    else None
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


def discover_provider_models(
    source: ProviderModelSource, *, timeout: float = DISCOVERY_TIMEOUT_SECONDS
) -> list[DiscoveredModel]:
    """Discover one provider's models, or ``[]`` if its credential is not registered."""
    api_key = get_credential(source.credential_name)
    if not api_key:
        return []
    url = source.list_url
    if source.task_filter:
        url = f"{url}?task={source.task_filter}"
    try:
        fetch = (
            _fetch_configured_gateway_json
            if source.provider_name == "configured_gateway"
            else _fetch_json
        )
        payload = fetch(
            url,
            api_key=api_key,
            auth_scheme=source.auth_scheme,
            timeout=timeout,
        )
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        # OSError covers ConnectionError/reset failures that are not URLError
        # subclasses, so a raw provider transport failure can never escape the
        # discovery boundary with provider text attached.
        raise ProviderDiscoveryError(source.provider_name, _provider_discovery_error_code(exc)) from None
    if source.provider_name == "opencode_zen":
        try:
            metadata = _fetch_json(_MODELS_DEV_URL, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            metadata = None
        payload = _merge_models_dev_metadata(payload, metadata, _MODELS_DEV_OPENCODE_PROVIDER)
    elif source.provider_name == "openrouter":
        try:
            metadata = _fetch_json(_OPENROUTER_ZDR_ENDPOINTS_URL, api_key=api_key, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            metadata = None
        payload = _merge_openrouter_zdr_metadata(payload, metadata)
    elif source.provider_name == "configured_gateway":
        try:
            metadata = _fetch_configured_gateway_json(
                f"{source.chat_base_url}/model/info",
                api_key=api_key,
                auth_scheme=source.auth_scheme,
                timeout=timeout,
            )
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            metadata = None
        payload = _merge_configured_gateway_metadata(payload, metadata)
    if source.style == "bytez":
        return _parse_bytez(payload, source)
    return _parse_openai_compatible(payload, source)


def discover_all_models(
    sources: tuple[ProviderModelSource, ...] = PROVIDER_MODEL_SOURCES,
    *,
    timeout: float = DISCOVERY_TIMEOUT_SECONDS,
) -> tuple[list[DiscoveredModel], list[ProviderDiscoveryError]]:
    """Discover models across every provider with a registered credential.

    One provider's failure never blocks the others: errors are collected and
    returned alongside whatever models were successfully discovered.
    """
    discovered: list[DiscoveredModel] = []
    errors: list[ProviderDiscoveryError] = []
    for source in sources:
        try:
            discovered.extend(discover_provider_models(source, timeout=timeout))
        except ProviderDiscoveryError as exc:
            errors.append(exc)
    return _deduplicate_discovered_models(discovered), errors


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    slug = _SLUG_RE.sub("_", value.lower()).strip("_")
    return slug or "model"


def agent_id_for(discovered: DiscoveredModel) -> str:
    """Two-or-more-word snake_case id, matching this repo's naming convention."""
    return f"{discovered.provider_name}_{_slug(discovered.model_id)}"


def agent_from_discovered(discovered: DiscoveredModel, *, priority: int = 0) -> ModelAgent:
    """Build a disabled capability agent or reject a chat-ineligible record."""
    if not any(capability != "chat" for capability in discovered.capabilities) and not (
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
            *discovered.capabilities,
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
        if is_general_chat_agent_model_id(model.model_id)
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
        if is_general_chat_agent_model_id(model.model_id)
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
        if is_general_chat_agent_model_id(model.model_id)
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
