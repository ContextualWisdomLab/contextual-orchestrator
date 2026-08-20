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
from dataclasses import dataclass
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


def _price_per_1k(value: Any) -> float | None:
    """OpenAI-compatible providers report USD price per single token; convert to per-1K."""
    if value is None or isinstance(value, bool):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price < 0:
        return None
    return price * 1000


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
    pricing is skipped rather than defaulted to zero. Discovery ranking treats
    that absence as unknown price evidence, never as proof that the model is free.
    """
    from .cost_ledger import PriceEntry

    claims: dict[tuple[str, str], list[tuple[float | None, float | None, str]]] = {}
    for model in discovered:
        identity = (model.provider_name, model.model_id)
        claims.setdefault(identity, []).append(
            (
                model.prompt_price_per_1k,
                model.completion_price_per_1k,
                model.currency_code,
            )
        )

    written = 0
    for (provider_name, model_name), rows in claims.items():
        if any(
            not _is_valid_price_component(value)
            for row in rows
            for value in row[:2]
        ) or any(row != rows[0] for row in rows[1:]):
            continue
        prompt_price, completion_price, currency_code = rows[0]
        if prompt_price is None or completion_price is None:
            continue
        price_book.set_price(
            PriceEntry(
                provider_name=provider_name,
                model_name=model_name,
                prompt_price_per_1k=prompt_price,
                completion_price_per_1k=completion_price,
                currency_code=currency_code,
            )
        )
        written += 1
    return written


def _is_valid_price_component(value: Any) -> bool:
    """Return whether one provider price is finite and non-negative."""
    return (
        value is not None
        and not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def _unique_discovered_models(
    discovered: list[DiscoveredModel],
) -> list[DiscoveredModel]:
    """Keep one deterministic row per provider/model serving identity."""
    unique: dict[tuple[str, str], DiscoveredModel] = {}
    for model in discovered:
        unique.setdefault((model.provider_name, model.model_id), model)
    return list(unique.values())


def _discovery_price_key(
    model: DiscoveredModel,
    price_book: "PriceBook",
) -> tuple[int, float, str, str]:
    """Rank known prices first, then deterministically order unknown prices."""
    entry = price_book.get_price(model.provider_name, model.model_id)
    if entry is None or not _is_trustworthy_price_entry(entry, price_book):
        return (1, 0.0, model.provider_name, model.model_id)
    cost, _currency = price_book.compute_cost(
        model.provider_name,
        model.model_id,
        1000,
        1000,
    )
    return (0, cost, model.provider_name, model.model_id)


def _is_trustworthy_price_entry(entry: Any, price_book: "PriceBook") -> bool:
    """Accept only complete, finite prices in the book's comparison currency."""
    return (
        entry.currency_code == price_book.default_currency
        and _is_valid_price_component(entry.prompt_price_per_1k)
        and _is_valid_price_component(entry.completion_price_per_1k)
    )


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
    unique = _unique_discovered_models(discovered)
    if not unique:
        return None
    return min(unique, key=lambda model: _discovery_price_key(model, price_book))


def select_top_n_cheapest_discovered_agents(
    discovered: list[DiscoveredModel], price_book: "PriceBook", limit: int
) -> list[DiscoveredModel]:
    """Return up to ``limit`` candidates with known prices before unknown ones."""
    if limit <= 0 or not discovered:
        return []
    discovered = _unique_discovered_models(discovered)
    return sorted(
        discovered,
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
    """
    if limit <= 0 or not discovered:
        return []
    discovered = _unique_discovered_models(discovered)

    ranked = sorted(
        discovered,
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
