"""Read-only price catalogue port and pre-call cost estimation.

The domain never reads the KV-backed ``cost_ledger.PriceBook`` directly; an
adapter implements :class:`PriceCatalog` over it (see
``contextual_orchestrator.spend_guard.PriceBookCatalog``), so the budget guard
and the usage ledger price calls from one source.
"""

from __future__ import annotations

from typing import Protocol

from .money import Money, Price, Usage

#: Endpoint schemes that execute locally and are never billed by a provider.
LOCAL_ENDPOINT_SCHEMES = ("mock://", "mlx://", "local://")


class PriceCatalog(Protocol):
    """Look up the configured price for one provider deployment."""

    def price_for(self, provider: str, model: str) -> Price | None:
        """Return the price, or ``None`` when it is not known."""
        ...


def effective_price(
    catalog: PriceCatalog,
    *,
    provider: str,
    model: str,
    base_url: str,
    tags: tuple[str, ...] = (),
) -> Price | None:
    """Price for a call: catalogue first, then local/zero-cost evidence, else unknown.

    Local endpoints are free because no provider bills them. A discovery
    ``cost:free`` tag (set only from exact-zero provider prices, ADR 0032) is
    zero-cost evidence when the catalogue has no row. Everything else without
    a catalogue row is unknown (``None``), never an invented zero.
    """
    if any(base_url.startswith(scheme) for scheme in LOCAL_ENDPOINT_SCHEMES):
        return Price.free()
    price = catalog.price_for(provider, model)
    if price is not None:
        return price
    if "cost:free" in tags:
        return Price.free()
    return None


def estimate_call_cost(price: Price | None, total_token_ceiling: int) -> Money | None:
    """Conservative cost ceiling for a provider-published total-token limit.

    The context window bounds input plus output tokens but does not determine
    their split. Pricing every token at the more expensive of the prompt and
    completion rates therefore bounds every possible split without guessing.
    """
    if price is None:
        return None
    token_ceiling = max(0, int(total_token_ceiling))
    prompt_only = price.cost_of(Usage(token_ceiling, 0, measured=False))
    completion_only = price.cost_of(Usage(0, token_ceiling, measured=False))
    return prompt_only if prompt_only >= completion_only else completion_only


__all__ = [
    "LOCAL_ENDPOINT_SCHEMES",
    "PriceCatalog",
    "effective_price",
    "estimate_call_cost",
]
