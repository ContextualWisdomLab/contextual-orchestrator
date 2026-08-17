"""Shared finite-price parsing and known-cost comparison.

Price honesty (issue #86) is used by discovery, ranking, and the ledger.
One helper keeps the four-way comparison from drifting across modules.
"""

from __future__ import annotations

from typing import Any


def optional_finite_price(value: Any) -> float | None:
    """Parse a finite non-negative price, or ``None`` if unknown.

    Booleans, non-numeric strings, negatives, NaN, infinities, and values
    that overflow ``float`` stay unknown — they are not coerced to ``0``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        value = stripped
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")) or parsed < 0:
        return None
    return parsed


def complete_pair_mean(prompt: float | None, completion: float | None) -> float | None:
    """Mean of a two-sided price, or ``None`` unless both sides are present.

    A prompt-only or completion-only row is unknown, not free.
    """
    if prompt is None or completion is None:
        return None
    return (prompt + completion) / 2.0


def known_comparison_cost(
    billed: float | None,
    listed: float | None,
    status: str | None = None,
) -> float | None:
    """Return the known ranking cost, or ``None`` if unpriced.

    Promotional-free billed ``0`` with a list price compares at the list
    price. Unpriced is never treated as ``0`` / free.
    """
    normalized = str(status or "unknown")
    if normalized == "unknown" and billed is None and listed is None:
        return None
    if billed == 0.0 and listed is not None:
        return listed
    if billed is not None:
        return billed
    return listed
