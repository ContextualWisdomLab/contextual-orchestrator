"""Money, usage, and price value objects for spend control.

Money uses :class:`decimal.Decimal` so small per-call costs accumulate
without binary floating-point drift, matching ``cost_ledger.PriceBook``.
Unknown is never zero: an absent price or absent usage is represented as
``None`` / ``measured=False`` by callers, never as a fabricated ``0``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import math
from typing import Any

DEFAULT_CURRENCY = "USD"
_QUANTUM = Decimal("0.000001")


def to_decimal(value: object) -> Decimal:
    """Parse a finite, non-negative monetary amount or raise ``ValueError``.

    ``bool`` is rejected even though Python treats it as an ``int``; floats go
    through ``str`` so ``0.1`` stays ``Decimal("0.1")``.
    """
    if isinstance(value, bool):
        raise ValueError("monetary amount must be a number, not a boolean")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("monetary amount must be finite")
        amount = Decimal(str(value))
    elif isinstance(value, str):
        try:
            amount = Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError("monetary amount is not a decimal number") from exc
    else:
        raise ValueError("monetary amount must be a number")
    if not amount.is_finite() or amount < 0:
        raise ValueError("monetary amount must be finite and non-negative")
    return amount


@dataclass(frozen=True, order=False)
class Money:
    """A non-negative amount in one currency."""

    amount: Decimal
    currency: str = DEFAULT_CURRENCY

    def __post_init__(self) -> None:
        """Normalize the amount and require an ISO-4217-like currency code."""
        object.__setattr__(self, "amount", to_decimal(self.amount))
        if (
            not isinstance(self.currency, str)
            or len(self.currency.strip()) != 3
            or not self.currency.strip().isalpha()
        ):
            raise ValueError("currency must be a three-letter code")
        object.__setattr__(self, "currency", self.currency.strip().upper())

    @classmethod
    def zero(cls, currency: str = DEFAULT_CURRENCY) -> "Money":
        """Return zero in ``currency``."""
        return cls(Decimal(0), currency)

    @classmethod
    def usd(cls, value: object) -> "Money":
        """Build a USD amount from a number or decimal string."""
        return cls(to_decimal(value), DEFAULT_CURRENCY)

    def _require_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError(
                f"cannot combine {self.currency} with {other.currency}; "
                "no exchange-rate evidence is available"
            )

    def __add__(self, other: "Money") -> "Money":
        """Add two amounts in the same currency."""
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def minus_floor_zero(self, other: "Money") -> "Money":
        """Subtract ``other`` but never go below zero (remaining budget)."""
        self._require_same_currency(other)
        return Money(max(Decimal(0), self.amount - other.amount), self.currency)

    def __lt__(self, other: "Money") -> bool:
        """Compare two amounts in the same currency."""
        self._require_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        """Compare two amounts in the same currency."""
        self._require_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: "Money") -> bool:
        """Compare two amounts in the same currency."""
        self._require_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: "Money") -> bool:
        """Compare two amounts in the same currency."""
        self._require_same_currency(other)
        return self.amount >= other.amount

    def scaled(self, ratio: Decimal) -> "Money":
        """Return this amount multiplied by a non-negative ratio."""
        return Money(self.amount * to_decimal(ratio), self.currency)

    def rounded(self) -> "Money":
        """Round half-up to six decimal places, like ``PriceBook``."""
        return Money(self.amount.quantize(_QUANTUM, rounding=ROUND_HALF_UP), self.currency)

    def as_float(self) -> float:
        """Return the six-decimal rounded amount as a JSON-friendly float."""
        return float(self.rounded().amount)


def _token_count(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class Usage:
    """Token usage for one provider call.

    ``measured`` is ``True`` only for provider-reported counts. Unmeasured usage
    keeps zero counts but callers must not treat it as a free call.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    measured: bool = False

    def __post_init__(self) -> None:
        """Reject negative, fractional, or boolean token counts."""
        _token_count(self.prompt_tokens, "prompt_tokens")
        _token_count(self.completion_tokens, "completion_tokens")
        if not isinstance(self.measured, bool):
            raise ValueError("measured must be a boolean")

    @classmethod
    def unavailable(cls) -> "Usage":
        """Return the explicit 'provider reported no usage' value."""
        return cls(0, 0, measured=False)

    @classmethod
    def from_provider_usage(cls, usage: Any) -> "Usage":
        """Parse an OpenAI-compatible ``usage`` object; malformed means unavailable.

        Accepts ``prompt_tokens``/``completion_tokens`` or the Responses API's
        ``input_tokens``/``output_tokens``. Both counts must be present
        non-negative integers; anything else is ``unavailable`` rather than a
        guessed zero.
        """
        if not isinstance(usage, dict):
            return cls.unavailable()
        prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
        completion = usage.get("completion_tokens", usage.get("output_tokens"))
        if (
            type(prompt) is not int
            or type(completion) is not int
            or prompt < 0
            or completion < 0
        ):
            return cls.unavailable()
        return cls(prompt, completion, measured=True)


def provider_reported_cost(usage: Any) -> Money | None:
    """Return a provider-reported charged cost (``usage.cost``) in USD, if valid.

    OpenRouter and Experiential Labs report the amount actually charged as a
    JSON number in ``usage.cost``. Only a real finite non-negative number is
    accepted; strings, booleans, and malformed values are ``None`` (unknown).
    BYOK calls (``usage.is_byok`` true) are billed by the upstream provider, so
    their gateway-reported cost is not treated as the charged amount.
    """
    if not isinstance(usage, dict):
        return None
    cost = usage.get("cost")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)):
        return None
    if isinstance(cost, float) and not math.isfinite(cost):
        return None
    if cost < 0 or usage.get("is_byok") is True:
        return None
    return Money.usd(cost)


@dataclass(frozen=True)
class Price:
    """Per-1K-token prompt and completion prices in one currency."""

    prompt_per_1k: Decimal
    completion_per_1k: Decimal
    currency: str = DEFAULT_CURRENCY

    def __post_init__(self) -> None:
        """Normalize price components and currency."""
        object.__setattr__(self, "prompt_per_1k", to_decimal(self.prompt_per_1k))
        object.__setattr__(self, "completion_per_1k", to_decimal(self.completion_per_1k))
        object.__setattr__(self, "currency", Money.zero(self.currency).currency)

    @classmethod
    def free(cls, currency: str = DEFAULT_CURRENCY) -> "Price":
        """Return an explicit zero price (evidence-backed free or local execution)."""
        return cls(Decimal(0), Decimal(0), currency)

    @classmethod
    def from_price_entry(cls, entry: Any) -> "Price":
        """Adapt a ``cost_ledger.PriceEntry``-shaped object without importing it."""
        return cls(
            to_decimal(entry.prompt_price_per_1k),
            to_decimal(entry.completion_price_per_1k),
            entry.currency_code,
        )

    @property
    def is_free(self) -> bool:
        """Whether both components are exactly zero."""
        return self.prompt_per_1k == 0 and self.completion_per_1k == 0

    def cost_of(self, usage: Usage) -> Money:
        """Return the rounded cost of ``usage`` at this price."""
        amount = (
            Decimal(usage.prompt_tokens) / Decimal(1000) * self.prompt_per_1k
            + Decimal(usage.completion_tokens) / Decimal(1000) * self.completion_per_1k
        )
        return Money(amount, self.currency).rounded()


__all__ = [
    "DEFAULT_CURRENCY",
    "Money",
    "Price",
    "Usage",
    "provider_reported_cost",
    "to_decimal",
]
