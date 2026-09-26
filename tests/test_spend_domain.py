"""Domain rules for money, spend limits, tenancy, and pricing (ADR 0138)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from contextual_orchestrator.cost_ledger import PriceEntry
from contextual_orchestrator.domain.budget import (
    BudgetExceededError,
    BudgetScope,
    CallPurpose,
    SpendLimit,
    SpendPosition,
    decide_affordability,
    parse_budget_duration,
)
from contextual_orchestrator.domain.money import Money, Price, Usage, provider_reported_cost
from contextual_orchestrator.domain.pricing import effective_price, estimate_call_cost
from contextual_orchestrator.domain.tenancy import (
    DEFAULT_TENANT_ID,
    TenantBudget,
    VirtualKey,
    hash_virtual_key,
    key_hash_matches,
    key_id_for_hash,
    validate_tenant_id,
)

SECRET = "sk-co-" + "a" * 40


def _position(scope: BudgetScope, max_cost: str | None, spent: str, **kwargs) -> SpendPosition:
    limit = SpendLimit(scope, f"{scope.value}_id", None if max_cost is None else Money.usd(max_cost), **kwargs)
    return SpendPosition(limit, Money.usd(spent))


# -- money -------------------------------------------------------------------

def test_money_arithmetic_is_decimal_and_currency_checked() -> None:
    """Money adds exactly and refuses mixed currencies."""
    assert (Money.usd("0.1") + Money.usd("0.2")).amount == Decimal("0.3")
    assert Money.usd(1).minus_floor_zero(Money.usd(3)) == Money.usd(0)
    with pytest.raises(ValueError):
        Money.usd(1) + Money(Decimal(1), "EUR")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "abc"])
def test_money_rejects_non_finite_negative_and_bool(bad: object) -> None:
    """Invalid amounts never become money."""
    with pytest.raises((ValueError, TypeError)):
        Money.usd(bad)


def test_usage_reads_both_token_vocabularies_and_flags_unavailable() -> None:
    """OpenAI chat and Responses usage shapes both map; anything else is unmeasured."""
    chat = Usage.from_provider_usage({"prompt_tokens": 10, "completion_tokens": 5})
    responses = Usage.from_provider_usage({"input_tokens": 7, "output_tokens": 3})
    assert (chat.prompt_tokens, chat.completion_tokens, chat.measured) == (10, 5, True)
    assert (responses.prompt_tokens, responses.completion_tokens) == (7, 3)
    assert Usage.from_provider_usage(None).measured is False
    assert Usage.from_provider_usage({"prompt_tokens": "10", "completion_tokens": 1}).measured is False


def test_provider_reported_cost_requires_real_number_and_skips_byok() -> None:
    """Only a numeric, non-negative ``usage.cost`` counts, and BYOK cost is not ours."""
    assert provider_reported_cost({"cost": 0.0123}) == Money.usd("0.0123")
    assert provider_reported_cost({"cost": "0.01"}) is None
    assert provider_reported_cost({"cost": True}) is None
    assert provider_reported_cost({"cost": -1}) is None
    assert provider_reported_cost({"cost": 0.5, "is_byok": True}) is None


def test_price_cost_of_uses_per_1k_rates() -> None:
    """A PriceBook row prices prompt and completion tokens separately."""
    price = Price.from_price_entry(PriceEntry("openai", "m", 0.5, 1.5))
    assert price.cost_of(Usage(1000, 2000)) == Money.usd("3.5")
    assert Price.free().is_free


# -- budget ------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "seconds"), [("30s", 30), ("5m", 300), ("2h", 7200), ("30d", 2592000), (None, None)]
)
def test_parse_budget_duration(text: str | None, seconds: int | None) -> None:
    """LiteLLM-style s/m/h/d durations parse to seconds."""
    assert parse_budget_duration(text) == seconds


@pytest.mark.parametrize("text", ["0d", "1w", "d", "-1h", "1.5h"])
def test_parse_budget_duration_rejects_invalid(text: str) -> None:
    """Unsupported units and non-positive values are rejected."""
    with pytest.raises(ValueError):
        parse_budget_duration(text)


def test_budget_window_rolls_forward_from_anchor() -> None:
    """Periodic budgets reset every duration after their creation time."""
    limit = SpendLimit(BudgetScope.TENANT, "t", Money.usd(1), budget_duration_seconds=100, anchor_epoch=1000)
    assert limit.window_start(1050) == 1000
    assert limit.window_start(1250) == 1200
    assert limit.reset_at(1250) == 1300
    assert SpendLimit(BudgetScope.RUN, "r", Money.usd(1)).window_start(5) is None


def test_no_limits_allows_everything() -> None:
    """Without positions every call is admitted, even with an unknown price."""
    assert decide_affordability([], estimate=None, now=0).allowed


def test_exhausted_budget_refuses_even_free_calls() -> None:
    """Spent >= max refuses with budget_exhausted and a LiteLLM-like message."""
    decision = decide_affordability(
        [_position(BudgetScope.RUN, "1", "1")], estimate=Money.usd(0), now=0
    )
    assert not decision.allowed and decision.reason == "budget_exhausted"
    with pytest.raises(BudgetExceededError, match="Budget has been exceeded!.*Max budget: 1.0"):
        decision.raise_if_refused()


def test_unknown_price_fails_closed_under_a_cap() -> None:
    """A billable call with no price is refused while any cap is active."""
    decision = decide_affordability([_position(BudgetScope.RUN, "1", "0")], estimate=None, now=0)
    assert decision.reason == "price_unknown"


def test_price_currency_mismatch_fails_closed_under_a_cap() -> None:
    """A price in another currency cannot be combined with a USD budget."""
    decision = decide_affordability(
        [_position(BudgetScope.RUN, "1", "0")],
        estimate=Money("0.1", "EUR"),
        now=0,
    )
    assert decision.reason == "price_currency_mismatch"


def test_insufficient_remaining_budget() -> None:
    """A call whose lower bound would cross the cap is refused before it is sent."""
    decision = decide_affordability(
        [_position(BudgetScope.RUN, "1", "0.9")], estimate=Money.usd("0.2"), now=0
    )
    assert decision.reason == "insufficient_remaining_budget"
    assert decision.detail["remaining_cost"] == pytest.approx(0.1)


def test_incomplete_measurement_blocks_billable_but_not_free_calls() -> None:
    """After an unmeasurable paid call, further paid calls fail closed; free ones proceed."""
    limit = SpendLimit(BudgetScope.RUN, "r", Money.usd(1))
    position = SpendPosition(limit, Money.usd(0), measurement_complete=False)
    assert decide_affordability([position], estimate=Money.usd("0.01"), now=0).reason == "measurement_unavailable"
    assert decide_affordability([position], estimate=Money.usd(0), now=0).allowed


def test_baseline_calls_are_skipped_first() -> None:
    """A paid baseline under a hard cap needs separate allocation authority."""
    positions = [_position(BudgetScope.RUN, "1", "0.45")]
    assert decide_affordability(positions, estimate=Money.usd("0.1"), now=0).allowed
    baseline = decide_affordability(
        positions, estimate=Money.usd("0.1"), now=0, purpose=CallPurpose.BASELINE
    )
    assert baseline.reason == "baseline_allocation_unavailable"
    assert decide_affordability(
        positions, estimate=Money.usd(0), now=0, purpose=CallPurpose.BASELINE
    ).allowed


def test_tightest_limit_wins_across_run_key_and_tenant() -> None:
    """When several limits refuse, the one with the least remaining budget is reported."""
    positions = [
        _position(BudgetScope.RUN, "10", "9.5"),
        _position(BudgetScope.VIRTUAL_KEY, "5", "4.9"),
        _position(BudgetScope.TENANT, "100", "99.8"),
    ]
    decision = decide_affordability(positions, estimate=Money.usd(1), now=0)
    assert decision.scope is BudgetScope.VIRTUAL_KEY
    only_tenant_refuses = [
        _position(BudgetScope.RUN, "10", "0"),
        _position(BudgetScope.TENANT, "1", "0.95"),
    ]
    assert decide_affordability(only_tenant_refuses, estimate=Money.usd("0.1"), now=0).scope is BudgetScope.TENANT


def test_tie_breaks_in_run_key_tenant_order() -> None:
    """Equal remaining budgets report the run scope first."""
    positions = [_position(BudgetScope.TENANT, "1", "1"), _position(BudgetScope.RUN, "1", "1")]
    assert decide_affordability(positions, estimate=Money.usd(0), now=0).scope is BudgetScope.RUN


def test_soft_budget_is_reported_without_blocking() -> None:
    """Crossing a soft budget alerts but still admits the call."""
    limit = SpendLimit(BudgetScope.TENANT, "acme", Money.usd(10), soft_max_cost=Money.usd(1))
    decision = decide_affordability([SpendPosition(limit, Money.usd(2))], estimate=Money.usd(1), now=0)
    assert decision.allowed and decision.soft_budget_crossed == ("tenant:acme",)


# -- tenancy -----------------------------------------------------------------

def test_virtual_key_hash_is_stable_and_never_the_secret() -> None:
    """Keys are stored as sha256 digests with a short non-secret id."""
    digest = hash_virtual_key(SECRET)
    assert digest.startswith("sha256:") and SECRET not in digest
    assert key_hash_matches(SECRET, digest)
    assert not key_hash_matches(SECRET + "x", digest)
    assert key_id_for_hash(digest).startswith("vk_") and len(key_id_for_hash(digest)) == 19


def test_short_virtual_key_is_rejected() -> None:
    """Low-entropy secrets cannot become virtual keys."""
    with pytest.raises(ValueError):
        hash_virtual_key("short")


@pytest.mark.parametrize("bad", ["", " spaced", "a" * 200, None, "bad\nid"])
def test_tenant_id_validation(bad: object) -> None:
    """Tenant ids are bounded identifier strings."""
    with pytest.raises((ValueError, TypeError)):
        validate_tenant_id(bad)
    assert validate_tenant_id("ContextualWisdomLab/repo") == "ContextualWisdomLab/repo"
    assert DEFAULT_TENANT_ID == "default"


def test_virtual_key_and_tenant_budget_round_trip() -> None:
    """Definitions serialize without secrets and rebuild identically."""
    key = VirtualKey(
        key_hash=hash_virtual_key(SECRET), tenant_id="acme", max_budget=Money.usd("2.5"),
        budget_duration_seconds=86400, soft_budget=Money.usd(1), created_at=100, key_alias="ci",
    )
    assert VirtualKey.from_dict(key.as_dict()) == key
    assert SECRET not in str(key.as_dict())
    assert key.spend_limit().scope is BudgetScope.VIRTUAL_KEY
    assert key.spend_limit().scope_id == key.key_id
    budget = TenantBudget(tenant_id="acme", max_budget=Money.usd(10), budget_duration_seconds=None, soft_budget=None, created_at=5)
    assert TenantBudget.from_dict(budget.as_dict()) == budget
    assert budget.spend_limit().scope is BudgetScope.TENANT


# -- pricing -----------------------------------------------------------------

class _Catalog:
    def __init__(self, prices: dict[tuple[str, str], Price]) -> None:
        self.prices = prices

    def price_for(self, provider: str, model: str) -> Price | None:
        return self.prices.get((provider, model))


def test_effective_price_prefers_catalog_then_local_then_free_tag() -> None:
    """Local endpoints are free, catalogue rows win, ``cost:free`` is zero-cost evidence."""
    paid = Price(Decimal("1"), Decimal("2"))
    catalog = _Catalog({("openai", "gpt"): paid})
    assert effective_price(catalog, provider="x", model="y", base_url="mock://local").is_free
    assert effective_price(catalog, provider="openai", model="gpt", base_url="https://a") == paid
    assert effective_price(catalog, provider="or", model="z", base_url="https://a", tags=("cost:free",)).is_free
    assert effective_price(catalog, provider="or", model="z", base_url="https://a") is None


def test_estimate_is_a_total_cost_upper_bound() -> None:
    """The known total-token ceiling is priced at the costlier token rate."""
    price = Price(Decimal("1"), Decimal("100"))
    assert estimate_call_cost(price, 2000) == Money.usd(200)
    assert estimate_call_cost(None, 2000) is None
