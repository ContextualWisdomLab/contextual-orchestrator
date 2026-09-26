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


def estimate_call_cost(price: Price | None, prompt_tokens_lower_bound: int) -> Money | None:
    """Lower-bound pre-call cost: prompt tokens only, since output is not known yet."""
    if price is None:
        return None
    return price.cost_of(Usage(max(0, int(prompt_tokens_lower_bound)), 0, measured=False))


__all__ = [
    "LOCAL_ENDPOINT_SCHEMES",
    "PriceCatalog",
    "effective_price",
    "estimate_call_cost",
]
