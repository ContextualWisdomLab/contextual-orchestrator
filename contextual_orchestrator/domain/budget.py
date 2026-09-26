"""Spend budgets: per-run cap, virtual-key budget, tenant budget.

One rule composes every active limit: a provider call is admitted only if
**every** applicable limit admits it, so the tightest limit wins. Limits are
evaluated with the same semantics regardless of scope:

* ``spent >= max`` refuses every further call (LiteLLM ``max_budget``
  semantics: an exhausted budget blocks, including zero-cost calls).
* ``spent + estimate > max`` refuses a call whose pre-call cost estimate no
  longer fits. The estimate is a lower bound (prompt side only), so an admitted
  call can still overshoot by at most its own output cost.
* An unknown price for a billable call refuses under any active cost cap
  (fail closed; unknown is never zero).
* Sampled baseline calls need extra headroom: they are admitted only while the
  remaining budget after the call stays at or above
  ``baseline_min_remaining_ratio`` of the cap, so baselines are the first work
  skipped when a budget runs short. They are charged to the same limits.
* ``soft_max`` never refuses; crossing it is reported so callers can alert.

This module is pure: callers pass the current spend and ``now``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import re
from typing import Any, Iterable

from .money import Money

#: Default share of a cap that must remain for a sampled baseline call.
DEFAULT_BASELINE_MIN_REMAINING_RATIO = Decimal("0.5")

_DURATION = re.compile(r"^\s*([1-9][0-9]{0,6})\s*([smhd])\s*$")
_DURATION_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class BudgetExceededError(RuntimeError):
    """Raised when an operator-configured spend budget refuses more spend.

    ``detail`` is a JSON-safe mapping describing which limit refused, its
    maximum, current spend, and reset time when known. The HTTP server maps
    this error to ``429 budget_exceeded``.
    """

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


class BudgetScope(str, Enum):
    """Which limit a budget decision is about; order is the tie-break order."""

    RUN = "run"
    VIRTUAL_KEY = "virtual_key"
    TENANT = "tenant"


class CallPurpose(str, Enum):
    """Why a provider call is made; baselines are skipped first when short."""

    PRIMARY = "primary"
    BASELINE = "baseline"


def parse_budget_duration(value: str | None) -> int | None:
    """Parse a LiteLLM-style ``budget_duration`` (``"30s"``, ``"30m"``, ``"30h"``, ``"30d"``).

    ``None`` or an empty string means the budget never resets. Anything else
    that does not match the grammar raises ``ValueError``.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise ValueError("budget_duration must be a string such as '30d'")
    match = _DURATION.match(value)
    if match is None:
        raise ValueError("budget_duration must look like 30s, 30m, 30h, or 30d")
    return int(match.group(1)) * _DURATION_SECONDS[match.group(2)]


@dataclass(frozen=True)
class SpendLimit:
    """One configured limit: a hard cap, an optional soft cap, an optional reset period."""

    scope: BudgetScope
    scope_id: str
    max_cost: Money | None
    soft_max_cost: Money | None = None
    budget_duration_seconds: int | None = None
    anchor_epoch: int = 0

    def __post_init__(self) -> None:
        """Validate the period and keep hard/soft caps in one currency."""
        if not isinstance(self.scope, BudgetScope):
            raise ValueError("scope must be a BudgetScope")
        if not isinstance(self.scope_id, str) or not self.scope_id:
            raise ValueError("scope_id must be a non-empty string")
        duration = self.budget_duration_seconds
        if duration is not None and (type(duration) is not int or duration <= 0):
            raise ValueError("budget_duration_seconds must be a positive integer")
        if type(self.anchor_epoch) is not int or self.anchor_epoch < 0:
            raise ValueError("anchor_epoch must be a non-negative integer")
        if (
            self.max_cost is not None
            and self.soft_max_cost is not None
            and self.max_cost.currency != self.soft_max_cost.currency
        ):
            raise ValueError("soft and hard caps must share a currency")

    def window_start(self, now: int) -> int | None:
        """Start of the current budget period, or ``None`` for an all-time budget.

        Periods are anchored at ``anchor_epoch`` (the budget's creation time)
        and repeat every ``budget_duration_seconds``, like LiteLLM's
        ``budget_reset_at`` roll-forward.
        """
        if self.budget_duration_seconds is None:
            return None
        if now <= self.anchor_epoch:
            return self.anchor_epoch
        elapsed_periods = (now - self.anchor_epoch) // self.budget_duration_seconds
        return self.anchor_epoch + elapsed_periods * self.budget_duration_seconds

    def reset_at(self, now: int) -> int | None:
        """When the current period's spend resets, or ``None`` if it never does."""
        start = self.window_start(now)
        if start is None or self.budget_duration_seconds is None:
            return None
        return start + self.budget_duration_seconds


@dataclass(frozen=True)
class SpendPosition:
    """A limit together with the spend already charged against it in this period.

    ``measurement_complete`` is ``False`` when a billable call in scope finished
    without measurable cost; under a cost cap that refuses further billable
    calls (fail closed).
    """

    limit: SpendLimit
    spent: Money
    measurement_complete: bool = True

    def remaining(self) -> Money | None:
        """Remaining hard budget, floored at zero; ``None`` without a hard cap."""
        if self.limit.max_cost is None:
            return None
        return self.limit.max_cost.minus_floor_zero(self.spent)


@dataclass(frozen=True)
class AffordabilityDecision:
    """Outcome of checking one prospective provider call against all limits."""

    allowed: bool
    reason: str = "within_budget"
    scope: BudgetScope | None = None
    scope_id: str | None = None
    soft_budget_crossed: tuple[str, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)

    def raise_if_refused(self) -> None:
        """Raise :class:`BudgetExceededError` with a LiteLLM-like message when refused."""
        if self.allowed:
            return
        spent = self.detail.get("spent_cost")
        maximum = self.detail.get("max_cost")
        scope = self.scope.value if self.scope is not None else "budget"
        message = (
            f"Budget has been exceeded! scope={scope} reason={self.reason} "
            f"Current cost: {spent}, Max budget: {maximum}"
        )
        raise BudgetExceededError(message, detail=dict(self.detail))


def _refusal(
    position: SpendPosition,
    reason: str,
    now: int,
    estimate: Money | None,
    purpose: CallPurpose,
) -> tuple[Decimal, int, AffordabilityDecision]:
    limit = position.limit
    maximum = limit.max_cost
    remaining = position.remaining()
    detail: dict[str, Any] = {
        "scope": limit.scope.value,
        "scope_id": limit.scope_id,
        "reason": reason,
        "purpose": purpose.value,
        "currency": maximum.currency if maximum is not None else None,
        "max_cost": maximum.as_float() if maximum is not None else None,
        "spent_cost": position.spent.as_float(),
        "remaining_cost": remaining.as_float() if remaining is not None else None,
        "estimated_call_cost": estimate.as_float() if estimate is not None else None,
        "budget_reset_at": limit.reset_at(now),
    }
    order = list(BudgetScope).index(limit.scope)
    tightness = remaining.amount if remaining is not None else Decimal(0)
    return tightness, order, AffordabilityDecision(
        allowed=False,
        reason=reason,
        scope=limit.scope,
        scope_id=limit.scope_id,
        detail=detail,
    )


def decide_affordability(
    positions: Iterable[SpendPosition],
    *,
    estimate: Money | None,
    now: int,
    purpose: CallPurpose = CallPurpose.PRIMARY,
    baseline_min_remaining_ratio: Decimal = DEFAULT_BASELINE_MIN_REMAINING_RATIO,
) -> AffordabilityDecision:
    """Admit or refuse one provider call against every active limit.

    ``estimate`` is the pre-call cost lower bound; ``None`` means the call is
    billable and its price is unknown. A known zero estimate is a free or local
    call. When several limits refuse, the one with the least remaining budget
    (the tightest) is reported; ties follow run, virtual key, tenant order.
    """
    ratio = Decimal(str(baseline_min_remaining_ratio))
    if ratio < 0 or ratio > 1:
        raise ValueError("baseline_min_remaining_ratio must be within [0, 1]")
    refusals: list[tuple[Decimal, int, AffordabilityDecision]] = []
    soft_crossed: list[str] = []
    for position in positions:
        limit = position.limit
        if limit.soft_max_cost is not None and position.spent >= limit.soft_max_cost:
            soft_crossed.append(f"{limit.scope.value}:{limit.scope_id}")
        maximum = limit.max_cost
        if maximum is None:
            continue
        if position.spent >= maximum:
            refusals.append(_refusal(position, "budget_exhausted", now, estimate, purpose))
            continue
        billable = estimate is None or estimate.amount > 0
        if estimate is None:
            refusals.append(_refusal(position, "price_unknown", now, estimate, purpose))
            continue
        if billable and not position.measurement_complete:
            refusals.append(
                _refusal(position, "measurement_unavailable", now, estimate, purpose)
            )
            continue
        after_call = position.spent + estimate
        if after_call > maximum:
            refusals.append(
                _refusal(position, "insufficient_remaining_budget", now, estimate, purpose)
            )
            continue
        if purpose is CallPurpose.BASELINE:
            remaining_after = maximum.minus_floor_zero(after_call)
            if remaining_after < maximum.scaled(ratio):
                refusals.append(
                    _refusal(position, "baseline_headroom_exhausted", now, estimate, purpose)
                )
    if refusals:
        refusals.sort(key=lambda item: (item[0], item[1]))
        decision = refusals[0][2]
        return AffordabilityDecision(
            allowed=False,
            reason=decision.reason,
            scope=decision.scope,
            scope_id=decision.scope_id,
            soft_budget_crossed=tuple(soft_crossed),
            detail={**decision.detail, "soft_budget_crossed": list(soft_crossed)},
        )
    return AffordabilityDecision(allowed=True, soft_budget_crossed=tuple(soft_crossed))


__all__ = [
    "AffordabilityDecision",
    "BudgetExceededError",
    "BudgetScope",
    "CallPurpose",
    "DEFAULT_BASELINE_MIN_REMAINING_RATIO",
    "SpendLimit",
    "SpendPosition",
    "decide_affordability",
    "parse_budget_duration",
]
