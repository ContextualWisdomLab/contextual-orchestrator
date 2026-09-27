"""Read-only price catalogue port and pre-call cost estimation.

The domain never reads the KV-backed ``cost_ledger.PriceBook`` directly; an
adapter implements :class:`PriceCatalog` over it (see
``contextual_orchestrator.spend_guard.PriceBookCatalog``), so the budget guard
and the usage ledger price calls from one source.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class AdmissionTokenBounds:
    """Per-request token upper bounds a caller can prove before sending.

    ``prompt_tokens`` must be an exact, provenance-bound count (never a lower
    bound) and ``max_output_tokens`` the output cap actually sent to the
    provider. ``None`` means unknown; admission then falls back to the
    model's ``context_window`` ceiling.
    """

    prompt_tokens: int | None = None
    max_output_tokens: int | None = None

    def usable(self) -> bool:
        """Whether both bounds are known and valid."""
        return (
            type(self.prompt_tokens) is int
            and self.prompt_tokens >= 0
            and type(self.max_output_tokens) is int
            and self.max_output_tokens > 0
        )


def estimate_request_cost(
    price: Price | None, prompt_tokens: int, max_output_tokens: int
) -> Money | None:
    """Cost ceiling from an exact prompt count and the enforced output cap.

    ``prompt_tokens`` x prompt price + ``max_output_tokens`` x completion
    price. Tighter than :func:`estimate_call_cost` whenever the request's
    own bounds are known; still an upper bound because the provider cannot
    bill more output than the ``max_tokens`` it was sent.
    """
    if price is None:
        return None
    return price.cost_of(
        Usage(max(0, int(prompt_tokens)), max(0, int(max_output_tokens)), measured=False)
    )


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
    "AdmissionTokenBounds",
    "PriceCatalog",
    "effective_price",
    "estimate_call_cost",
    "estimate_request_cost",
]
