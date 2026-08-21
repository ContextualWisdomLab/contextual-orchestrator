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

import re
import urllib.error
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .batch_routing import cheapest_upstream
from .credentials import get_credential
from .orchestrator import ModelAgent, ModelClient

if TYPE_CHECKING:
    from .cost_ledger import PriceBook

DISCOVERY_TIMEOUT_SECONDS = 15.0


def _provider_discovery_error_code(exc: Exception) -> str:
    """Map provider failures to stable codes without retaining provider response text."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"http_status_{exc.code}"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.URLError) or isinstance(exc, OSError):
        return "transport_error"
    if isinstance(exc, ValueError):
        return "invalid_response"
    return "provider_error"


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
        list_url="https://openrouter.ai/api/v1/models",
        chat_base_url="https://openrouter.ai/api/v1",
    ),
    ProviderModelSource(
        provider_name="nvidia_nim",
        credential_name="NVIDIA_NIM_API_KEY",
        list_url="https://integrate.api.nvidia.com/v1/models",
        chat_base_url="https://integrate.api.nvidia.com/v1",
    ),
    ProviderModelSource(
        provider_name="nvidia_nim_sub",
        credential_name="NVIDIA_NIM_API_KEY_SUB",
        list_url="https://integrate.api.nvidia.com/v1/models",
        chat_base_url="https://integrate.api.nvidia.com/v1",
    ),
    ProviderModelSource(
        provider_name="bytez",
        credential_name="BYTEZ_API_KEY",
        list_url="https://api.bytez.com/models/v2/list/models",
        chat_base_url="https://api.bytez.com/models/v2/openai/v1",
        auth_scheme="Key",
        style="bytez",
        task_filter="chat",
    ),
)


@dataclass(frozen=True)
class DiscoveredModel:
    """One model found on a provider, with pricing when the provider reports it."""

    provider_name: str
    model_id: str
    credential_name: str
    chat_base_url: str
    auth_scheme: str
    prompt_price_per_1k: float | None = None
    completion_price_per_1k: float | None = None
    currency_code: str = "USD"


class ProviderDiscoveryError(RuntimeError):
    """Raised when a provider's model list could not be fetched (network/auth failure)."""

    def __init__(self, provider_name: str, error_code: str) -> None:
        self.provider_name = provider_name
        self.error_code = error_code
        super().__init__(f"model discovery failed for provider {provider_name!r}: {error_code}")


def _fetch_json(
    url: str,
    *,
    auth_scheme: str,
    timeout: float,
    credential_name: str,
) -> Any:
    """Fetch a provider catalog through the validated, DNS-pinned transport."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("model discovery requires an https provider URL")
    if parsed.username is not None or parsed.password is not None or "#" in url:
        raise ValueError("model discovery URL must not contain credentials or a fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("model discovery URL has an invalid port") from exc
    origin = f"https://{parsed.hostname}"
    if port not in (None, 443):
        origin = f"{origin}:{port}"
    agent = ModelAgent(
        id="model_discovery_agent",
        model="model_catalog",
        base_url=origin,
        credential_key=credential_name,
        auth_scheme=auth_scheme,
    )
    client = ModelClient()
    return client.fetch_json(agent, url, timeout=timeout)


def _price_per_1k(value: Any) -> float | None:
    """OpenAI-compatible providers report USD price per single token; convert to per-1K."""
    if value is None:
        return None
    try:
        return float(value) * 1000
    except (TypeError, ValueError):
        return None


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
        discovered.append(
            DiscoveredModel(
                provider_name=source.provider_name,
                model_id=model_id,
                credential_name=source.credential_name,
                chat_base_url=source.chat_base_url,
                auth_scheme=source.auth_scheme,
                prompt_price_per_1k=_price_per_1k(pricing.get("prompt")),
                completion_price_per_1k=_price_per_1k(pricing.get("completion")),
            )
        )
    return discovered


def _parse_bytez(payload: Any, source: ProviderModelSource) -> list[DiscoveredModel]:
    rows = payload.get("output") if isinstance(payload, dict) else None
    discovered: list[DiscoveredModel] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        model_id = row.get("modelId")
        if type(model_id) is not str or not model_id:
            continue
        discovered.append(
            DiscoveredModel(
                provider_name=source.provider_name,
                model_id=model_id,
                credential_name=source.credential_name,
                chat_base_url=source.chat_base_url,
                auth_scheme=source.auth_scheme,
                # Bytez prices by GPU-second (meterPrice), not per-token; leaving
                # per-1k pricing unset is more honest than a misleading estimate.
            )
        )
    return discovered


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
        payload = _fetch_json(
            url,
            auth_scheme=source.auth_scheme,
            timeout=timeout,
            credential_name=source.credential_name,
        )
    except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError, OSError) as exc:  # pragma: no cover - network path
        raise ProviderDiscoveryError(source.provider_name, _provider_discovery_error_code(exc)) from None
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
    return discovered, errors


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    slug = _SLUG_RE.sub("_", value.lower()).strip("_")
    return slug or "model"


def agent_id_for(discovered: DiscoveredModel) -> str:
    """Two-or-more-word snake_case id, matching this repo's naming convention."""
    return f"{discovered.provider_name}_{_slug(discovered.model_id)}"


def agent_from_discovered(discovered: DiscoveredModel, *, priority: int = 0) -> ModelAgent:
    """Build a disabled-by-default ModelAgent for a discovered model (opt-in serving)."""
    return ModelAgent(
        id=agent_id_for(discovered),
        model=discovered.model_id,
        base_url=discovered.chat_base_url,
        credential_key=discovered.credential_name,
        auth_scheme=discovered.auth_scheme,
        provider_name=discovered.provider_name,
        tags=("discovered",),
        priority=priority,
        disabled=True,
    )


def refresh_price_book(discovered: list[DiscoveredModel], price_book: "PriceBook") -> int:
    """Write every discovered model's known pricing into the price book.

    Returns the number of price rows written. A model without provider-reported
    pricing is skipped rather than defaulted to 0 -- an unpriced model already
    costs 0 under ``PriceBook.compute_cost``'s "explicit, not silently expensive"
    contract, so writing a fabricated 0 row here would just hide that signal.
    """
    from .cost_ledger import PriceEntry

    written = 0
    for model in discovered:
        if model.prompt_price_per_1k is None and model.completion_price_per_1k is None:
            continue
        price_book.set_price(
            PriceEntry(
                provider_name=model.provider_name,
                model_name=model.model_id,
                prompt_price_per_1k=model.prompt_price_per_1k or 0.0,
                completion_price_per_1k=model.completion_price_per_1k or 0.0,
                currency_code=model.currency_code,
            )
        )
        written += 1
    return written


def select_cheapest_discovered_agent(
    discovered: list[DiscoveredModel], price_book: "PriceBook"
) -> DiscoveredModel | None:
    """Pick the lowest-cost discovered model per the price book (auto-optimization).

    Reuses :func:`~contextual_orchestrator.batch_routing.cheapest_upstream`, the
    existing cost-optimizing upstream selector. Call :func:`refresh_price_book`
    first so discovered pricing is visible; an unpriced candidate costs ``0``
    under that selector's documented contract and is treated as free, not
    unknown -- so a genuinely unpriced provider (e.g. Bytez, priced by
    GPU-second rather than per token) will always look cheapest here. Fine for
    "auto-pick something free to try," but callers doing real cost comparison
    should refresh pricing for every candidate they care about first.
    """
    if not discovered:
        return None
    candidates = [{"provider": model.provider_name, "model": model.model_id} for model in discovered]
    winner = cheapest_upstream(candidates, price_book)
    if winner is None:
        return None
    for model in discovered:
        if model.provider_name == winner["provider"] and model.model_id == winner["model"]:
            return model
    return None  # pragma: no cover - winner always comes from candidates


def select_top_n_cheapest_discovered_agents(
    discovered: list[DiscoveredModel], price_book: "PriceBook", limit: int
) -> list[DiscoveredModel]:
    """Return the ``limit`` lowest-cost discovered models, cheapest first.

    For bootstrapping a CI sidecar (or any first-boot pool) with more than one
    enabled agent for failover, without hand-picking which discovered models to
    trust. Same pricing contract as :func:`select_cheapest_discovered_agent`.
    """
    if limit <= 0 or not discovered:
        return []

    def _cost(model: DiscoveredModel) -> float:
        cost, _currency = price_book.compute_cost(model.provider_name, model.model_id, 1000, 1000)
        return cost

    return sorted(discovered, key=_cost)[:limit]
