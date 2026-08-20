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

import json
import math
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from .credentials import get_credential
from .orchestrator import ModelAgent

if TYPE_CHECKING:
    from .cost_ledger import PriceBook

DISCOVERY_TIMEOUT_SECONDS = 15.0


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

    def __init__(self, provider_name: str, detail: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"model discovery failed for provider {provider_name!r}: {detail}")


def _fetch_json(url: str, *, api_key: str, auth_scheme: str, timeout: float) -> Any:
    if not url.startswith("https://"):
        # Every caller passes one of the hardcoded PROVIDER_SOURCES chat_base_url
        # constants below, never external input -- but urlopen also honors
        # file:// and other unsafe schemes, so refuse anything not https as a
        # cheap invariant check rather than trusting the constant list alone.
        raise ValueError(f"refusing non-https model discovery URL: {url!r}")
    request = urllib.request.Request(
        url,
        headers={"authorization": f"{auth_scheme} {api_key}"},
        method="GET",
    )
    # Scheme is enforced to https:// immediately above; url is never attacker-controlled.
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https provider hosts  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        return json.loads(response.read().decode("utf-8"))


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
    """Convert a trustworthy per-token USD price to per-1K, else return unknown."""
    if value is None or isinstance(value, bool):
        return None
    try:
        per_1k = float(value) * 1000
    except (TypeError, ValueError, OverflowError):
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
        payload = _fetch_json(url, api_key=api_key, auth_scheme=source.auth_scheme, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:  # pragma: no cover - network path
        raise ProviderDiscoveryError(source.provider_name, str(exc)) from exc
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
        return unknown
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
    eligible = _deduplicate_discovered_models(discovered)
    if not eligible:
        return None
    return min(eligible, key=lambda model: _discovery_price_key(model, price_book))


def select_top_n_cheapest_discovered_agents(
    discovered: list[DiscoveredModel], price_book: "PriceBook", limit: int
) -> list[DiscoveredModel]:
    """Return up to ``limit`` unique candidates, known-priced before unknown."""
    if limit <= 0:
        return []
    eligible = _deduplicate_discovered_models(discovered)
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
    eligible = _deduplicate_discovered_models(discovered)
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
