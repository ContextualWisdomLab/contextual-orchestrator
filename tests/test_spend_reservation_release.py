"""Unknown-outcome reservations never lock a budget forever (ADR 0138).

Covers the operator settlement path (function and CLI), window expiry of
stale reservations, surfacing of the original provider error in
``measurement_unavailable`` refusals, and the narrowed admission bound.
Every provider is faked; no live or paid provider is called.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from contextual_orchestrator import __main__ as cli
from contextual_orchestrator import orchestrator as orchestrator_module
from contextual_orchestrator.cost_ledger import PriceBook, PriceEntry
from contextual_orchestrator.domain.budget import BudgetExceededError
from contextual_orchestrator.domain.money import Money, Price
from contextual_orchestrator.domain.pricing import (
    AdmissionTokenBounds,
    estimate_request_cost,
)
from contextual_orchestrator.kv_config import InMemoryConfigStore
from contextual_orchestrator.orchestrator import (
    ModelAgent,
    ModelClient,
    TaskOrchestrator,
)
from contextual_orchestrator.provider_errors import classify_provider_failure
from contextual_orchestrator.spend_guard import (
    SpendGuard,
    SpendGuardConfig,
    guarded_provider_call,
)
from contextual_orchestrator.spend_metering import (
    InMemorySpendLedgerStore,
    JsonlSpendLedgerStore,
    SpendSettlement,
    active_reservation_report,
    operator_settle_reservation,
)
from contextual_orchestrator.token_counting import MessageCountResult

PAID = ModelAgent(
    "openai_paid_agent",
    "gpt-paid",
    base_url="https://api.openai.test/v1",
    provider_name="openai",
    context_window=2000,
)
NO_WINDOW = ModelAgent(
    "openai_no_window_agent",
    "gpt-paid",
    base_url="https://api.openai.test/v1",
    provider_name="openai",
)
USAGE = {"prompt_tokens": 1000, "completion_tokens": 1000}
PROMPT = [{"role": "user", "content": "hello there"}]
HOUR = 3600


def _price_book() -> PriceBook:
    book = PriceBook(InMemoryConfigStore())
    book.set_price(PriceEntry("openai", "gpt-paid", 1.0, 1.0))  # $1/1k tokens each way
    return book


class _Clock:
    def __init__(self, now: float = 1_700_000_000) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _provider_500() -> BaseException:
    """A classified provider 500 whose outcome (billed or not) is unknown."""
    return classify_provider_failure(
        urllib.error.HTTPError(
            "https://provider.test/v1/chat/completions",
            500,
            "internal error",
            {},
            io.BytesIO(b'{"error": {"message": "upstream exploded"}}'),
        ),
        agent_id=PAID.id,
        model=PAID.model,
    )


BOOM_TYPE = type(_provider_500()).__name__


def _fail_unknown(guard: SpendGuard, tenant: str = "acme") -> None:
    with (
        guard.tenant_context(tenant_id=tenant),
        guard.run_scope(),
        pytest.raises(type(_provider_500())),
    ):
        guarded_provider_call(
            PAID,
            PROMPT,
            lambda: (_ for _ in ()).throw(_provider_500()),
            usage_reader=None,
        )


def _call_ok(guard: SpendGuard, tenant: str = "acme", **kwargs) -> str:
    with guard.tenant_context(tenant_id=tenant), guard.run_scope():
        return guarded_provider_call(
            PAID, PROMPT, lambda: "answer", usage_reader=lambda: USAGE, **kwargs
        )


# -- operator settlement ----------------------------------------------------


def test_operator_settlement_unlocks_an_all_time_budget_across_processes(
    tmp_path: Path,
) -> None:
    """All-time budgets stay fail-closed until an explicit, reasoned settlement."""
    ledger = tmp_path / "ledger.jsonl"
    guard = SpendGuard(price_book=_price_book(), store=JsonlSpendLedgerStore(ledger))
    guard.set_tenant_budget("acme", max_budget_usd="10")
    _fail_unknown(guard)

    blocked = SpendGuard(price_book=_price_book(), store=JsonlSpendLedgerStore(ledger))
    with pytest.raises(BudgetExceededError) as refused:
        _call_ok(blocked)
    assert refused.value.detail["reason"] == "measurement_unavailable"

    operator_store = JsonlSpendLedgerStore(ledger)
    [reservation] = active_reservation_report(operator_store)
    assert reservation["calls"][0]["error_type"] == BOOM_TYPE
    assert reservation["calls"][0]["provider_status"] == 500
    settlement = operator_settle_reservation(
        operator_store,
        reservation["reservation_id"],
        settled_cost=Money.usd("1.25"),
        reason="provider invoice shows 1.25 USD for the failed request",
        settled_by="oncall@example.test",
        now=1_700_000_100,
    )
    assert settlement.settled_cost == Money.usd("1.25")
    assert operator_store.active_spend_reservations() == []

    reloaded = SpendGuard(price_book=_price_book(), store=JsonlSpendLedgerStore(ledger))
    assert _call_ok(reloaded) == "answer"
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    settle_events = [event for event in events if event["event"] == "spend_settlement"]
    assert len(settle_events) == 1
    assert settle_events[0]["data"]["reason"].startswith("provider invoice")
    assert settle_events[0]["data"]["settled_by"] == "oncall@example.test"
    assert list(reloaded.store.spend_settlements()) == [reservation["reservation_id"]]


def test_settled_cost_counts_against_the_budget() -> None:
    """A settlement is spend, not forgiveness: the settled cost stays charged."""
    guard = SpendGuard(price_book=_price_book(), store=InMemorySpendLedgerStore())
    guard.set_tenant_budget("acme", max_budget_usd="3")
    _fail_unknown(guard)
    [reservation] = guard.store.active_spend_reservations()
    operator_settle_reservation(
        guard.store,
        reservation.reservation_id,
        settled_cost=Money.usd("2"),
        reason="provider dashboard charged the full request",
        settled_by="oncall",
        now=guard.now(),
    )
    with pytest.raises(BudgetExceededError) as refused:
        _call_ok(guard)  # $2 settled + $4 ceiling > $3
    assert refused.value.detail["reason"] != "measurement_unavailable"


def test_settlement_requires_reason_and_operator_and_active_reservation() -> None:
    """No silent release: reason, operator, and a live reservation are mandatory."""
    guard = SpendGuard(price_book=_price_book(), store=InMemorySpendLedgerStore())
    guard.set_tenant_budget("acme", max_budget_usd="10")
    _fail_unknown(guard)
    [reservation] = guard.store.active_spend_reservations()
    for reason, operator in (
        ("", "oncall"),
        ("   ", "oncall"),
        ("reason", ""),
        ("reason", " "),
    ):
        with pytest.raises(ValueError):
            operator_settle_reservation(
                guard.store,
                reservation.reservation_id,
                settled_cost=Money.zero("USD"),
                reason=reason,
                settled_by=operator,
                now=guard.now(),
            )
    with pytest.raises(ValueError):
        operator_settle_reservation(
            guard.store,
            reservation.reservation_id,
            settled_cost=Money.usd("-1"),
            reason="negative",
            settled_by="oncall",
            now=guard.now(),
        )
    with pytest.raises(LookupError):
        operator_settle_reservation(
            guard.store,
            "no-such-reservation",
            settled_cost=Money.zero("USD"),
            reason="typo",
            settled_by="oncall",
            now=guard.now(),
        )
    settlement = SpendSettlement.for_reservation(
        reservation,
        settled_cost=Money.zero("USD"),
        settled_at=guard.now(),
        settled_by="oncall",
        reason="provider confirmed the 500 was not billed",
    )
    assert guard.store.settle_spend_reservation(settlement) is True
    assert guard.store.settle_spend_reservation(settlement) is False
    assert SpendSettlement.from_dict(settlement.as_dict()) == settlement


def test_cli_lists_and_settles_reservations(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """``spend-reservations`` and ``spend-settle`` are the operator release path."""
    ledger = tmp_path / "ledger.jsonl"
    guard = SpendGuard(price_book=_price_book(), store=JsonlSpendLedgerStore(ledger))
    guard.set_tenant_budget("acme", max_budget_usd="10")
    _fail_unknown(guard)

    monkeypatch.setattr(
        sys, "argv", ["prog", "spend-reservations", "--spend-ledger-path", str(ledger)]
    )
    cli.main()
    listed = json.loads(capsys.readouterr().out)["active_reservations"]
    assert len(listed) == 1
    reservation_id = listed[0]["reservation_id"]

    base = [
        "prog",
        "spend-settle",
        "--spend-ledger-path",
        str(ledger),
        "--reservation-id",
    ]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            *base,
            reservation_id,
            "--settled-cost-usd",
            "0",
            "--operator",
            "oncall",
            "--reason",
            " ",
        ],
    )
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 2
    assert "reason" in capsys.readouterr().err

    monkeypatch.setattr(
        sys,
        "argv",
        [
            *base,
            "nope",
            "--settled-cost-usd",
            "0",
            "--operator",
            "oncall",
            "--reason",
            "typo",
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()
    assert "no active spend reservation" in capsys.readouterr().err

    monkeypatch.setattr(
        sys,
        "argv",
        [
            *base,
            reservation_id,
            "--settled-cost-usd",
            "0",
            "--operator",
            "oncall",
            "--reason",
            "provider support confirmed the 500 was not billed",
        ],
    )
    cli.main()
    settled = json.loads(capsys.readouterr().out)["spend_settlement"]
    assert settled["reservation_id"] == reservation_id
    assert settled["settled_by"] == "oncall"
    assert JsonlSpendLedgerStore(ledger).active_spend_reservations() == []
    assert (
        _call_ok(
            SpendGuard(price_book=_price_book(), store=JsonlSpendLedgerStore(ledger))
        )
        == "answer"
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "spend-reservations",
            "--spend-ledger-path",
            str(tmp_path / "missing.jsonl"),
        ],
    )
    with pytest.raises(SystemExit):
        cli.main()


# -- window expiry -----------------------------------------------------------


def test_windowed_budget_expires_a_stale_unknown_reservation() -> None:
    """With ``budget_duration`` the lock ends at the window boundary; all-time stays closed."""
    clock = _Clock()
    store = InMemorySpendLedgerStore()
    guard = SpendGuard(price_book=_price_book(), store=store, clock=clock)
    guard.set_tenant_budget("hourly", max_budget_usd="10", budget_duration="1h")
    guard.set_tenant_budget("forever", max_budget_usd="10")
    _fail_unknown(guard, "hourly")
    _fail_unknown(guard, "forever")

    for tenant in ("hourly", "forever"):
        with pytest.raises(BudgetExceededError) as refused:
            _call_ok(guard, tenant)
        assert refused.value.detail["reason"] == "measurement_unavailable"

    clock.now += HOUR
    assert _call_ok(guard, "hourly") == "answer"
    with pytest.raises(BudgetExceededError) as still_refused:
        _call_ok(guard, "forever")
    assert still_refused.value.detail["reason"] == "measurement_unavailable"


# -- error surfacing ---------------------------------------------------------


def test_measurement_unavailable_names_the_original_provider_error_in_run() -> None:
    """In-run retries after an unknown outcome chain the provider error as the cause."""
    client = ModelClient()
    calls: list[str] = []

    def transport(agent, messages, temperature=None, top_p=None, effort_profile=None):
        calls.append(agent.provider_name)
        client._local.usage = None
        raise _provider_500()

    client._chat_transport = transport  # type: ignore[method-assign]
    guard = SpendGuard(price_book=_price_book(), store=InMemorySpendLedgerStore())
    guard.set_tenant_budget("acme", max_budget_usd="100")
    orch = TaskOrchestrator(
        [PAID], client=client, spend_guard=guard, rate_limit_wait_seconds=0.0
    )
    orch.policy = replace(orch.policy, realtime_judge=False)
    with (
        guard.tenant_context(tenant_id="acme"),
        pytest.raises(BudgetExceededError) as raised,
    ):
        orch.route_once(PROMPT)
    assert calls == ["openai"]
    assert raised.value.detail["reason"] == "measurement_unavailable"
    assert type(raised.value.__cause__).__name__ == BOOM_TYPE
    assert f"{BOOM_TYPE}: upstream exploded" in str(raised.value)
    [refusal] = guard.last_run_summary()["budget"]["refusals"]
    assert refusal["unmeasured_calls"][0]["provider_status"] == 500
    assert "upstream exploded" in refusal["unmeasured_calls"][0]["error_message"]


def test_cross_process_refusal_names_the_ledgered_provider_error(
    tmp_path: Path,
) -> None:
    """A later process sees the recorded error class and HTTP status, not only the symptom."""
    ledger = tmp_path / "ledger.jsonl"
    guard = SpendGuard(price_book=_price_book(), store=JsonlSpendLedgerStore(ledger))
    guard.set_tenant_budget("acme", max_budget_usd="100")
    _fail_unknown(guard)

    other = SpendGuard(price_book=_price_book(), store=JsonlSpendLedgerStore(ledger))
    with pytest.raises(BudgetExceededError) as refused:
        _call_ok(other)
    assert refused.value.detail["reason"] == "measurement_unavailable"
    assert BOOM_TYPE in str(refused.value)
    assert "status=500" in str(refused.value)
    [call] = refused.value.detail["unmeasured_calls"]
    assert call["error_type"] == BOOM_TYPE
    assert call["provider_status"] == 500
    assert call["reservation_id"]


def test_in_run_refusal_chains_the_provider_error() -> None:
    """The same run's retry raises a refusal whose ``__cause__`` is the provider error."""
    guard = SpendGuard(price_book=_price_book(), store=InMemorySpendLedgerStore())
    guard.set_tenant_budget("acme", max_budget_usd="100")
    boom = _provider_500()
    with guard.tenant_context(tenant_id="acme"), guard.run_scope():
        with pytest.raises(type(boom)):
            guarded_provider_call(
                PAID, PROMPT, lambda: (_ for _ in ()).throw(boom), usage_reader=None
            )
        with pytest.raises(BudgetExceededError) as refused:
            guarded_provider_call(
                PAID, PROMPT, lambda: "answer", usage_reader=lambda: USAGE
            )
    assert refused.value.__cause__ is boom
    assert f"{BOOM_TYPE}:" in str(refused.value)
    assert refused.value.detail["unmeasured_calls"][0]["error_type"] == BOOM_TYPE


# -- narrowed admission bound ------------------------------------------------


def test_request_cost_estimate_is_prompt_times_prompt_price_plus_output_cap() -> None:
    price = Price(Decimal("0.5"), Decimal(2))
    assert estimate_request_cost(price, 1000, 250) == Money.usd("1.0")
    assert estimate_request_cost(None, 1, 1) is None
    assert AdmissionTokenBounds(10, 5).usable()
    assert not AdmissionTokenBounds(None, 5).usable()
    assert not AdmissionTokenBounds(10, None).usable()
    assert not AdmissionTokenBounds(10, 0).usable()
    assert not AdmissionTokenBounds(True, 5).usable()  # type: ignore[arg-type]


def test_narrow_bound_admits_where_the_context_ceiling_would_refuse() -> None:
    """$4 ceiling (2000 tokens x $2/1k) exceeds a $1 cap; 100+200 tokens ($0.30) fits."""
    guard = SpendGuard(
        config=SpendGuardConfig.from_values(run_max_cost_usd=1),
        price_book=_price_book(),
    )
    with guard.run_scope():
        answer = guarded_provider_call(
            PAID,
            PROMPT,
            lambda: "answer",
            usage_reader=lambda: {"prompt_tokens": 100, "completion_tokens": 150},
            token_bounds=lambda: AdmissionTokenBounds(
                prompt_tokens=100, max_output_tokens=200
            ),
        )
    assert answer == "answer"
    with guard.run_scope(), pytest.raises(BudgetExceededError) as refused:
        guarded_provider_call(
            PAID, PROMPT, lambda: "answer", usage_reader=lambda: USAGE
        )
    assert refused.value.detail["estimate_source"] == "context_window_ceiling"


def test_unknown_bounds_fall_back_to_the_ceiling_and_fail_closed_without_one() -> None:
    guard = SpendGuard(
        config=SpendGuardConfig.from_values(run_max_cost_usd=1),
        price_book=_price_book(),
    )

    def half_known() -> AdmissionTokenBounds:
        return AdmissionTokenBounds(prompt_tokens=None, max_output_tokens=200)

    with guard.run_scope(), pytest.raises(BudgetExceededError) as ceiling:
        guarded_provider_call(
            PAID,
            PROMPT,
            lambda: "answer",
            usage_reader=None,
            token_bounds=half_known,
        )
    assert ceiling.value.detail["estimate_source"] == "context_window_ceiling"
    assert ceiling.value.detail["max_output_tokens_bound"] == 200

    with guard.run_scope(), pytest.raises(BudgetExceededError) as missing:
        guarded_provider_call(NO_WINDOW, PROMPT, lambda: "answer", usage_reader=None)
    assert missing.value.detail["reason"] == "missing_context_window"

    # Known bounds rescue a route with no context window.
    with guard.run_scope():
        assert (
            guarded_provider_call(
                NO_WINDOW,
                PROMPT,
                lambda: "answer",
                usage_reader=lambda: {"prompt_tokens": 10, "completion_tokens": 10},
                token_bounds=lambda: AdmissionTokenBounds(10, 100),
            )
            == "answer"
        )

    def broken() -> AdmissionTokenBounds:
        raise RuntimeError("counter crashed")

    with guard.run_scope(), pytest.raises(BudgetExceededError) as broken_bounds:
        guarded_provider_call(
            NO_WINDOW,
            PROMPT,
            lambda: "answer",
            usage_reader=None,
            token_bounds=broken,
        )
    assert broken_bounds.value.detail["reason"] == "missing_context_window"


def test_narrow_bound_never_exceeds_the_context_ceiling() -> None:
    """An output cap above the window cannot loosen admission past the ceiling."""
    guard = SpendGuard(
        config=SpendGuardConfig.from_values(run_max_cost_usd=100),
        price_book=_price_book(),
    )
    with guard.run_scope() as scope:
        guarded_provider_call(
            PAID,
            PROMPT,
            lambda: "answer",
            usage_reader=lambda: USAGE,
            token_bounds=lambda: AdmissionTokenBounds(1500, 100_000),
        )
        assert scope.spent == Money.usd("2")


class _ExactCounter:
    """Stub provenance-exact counter so the orchestrator can prove the prompt size."""

    def count_messages(self, messages, model, *, tools=None):
        return 100

    def describe_messages(self, messages, model, *, tools=None):
        return MessageCountResult(
            100, model, "stub-tokenizer", "stub-framing", "https://tokenizer.test"
        )


def test_orchestrator_passes_exact_prompt_and_output_cap_to_admission(
    monkeypatch,
) -> None:
    """ModelClient.chat bounds admission by the exact prompt and the max_tokens it sends."""
    monkeypatch.setattr(
        orchestrator_module, "_resolve_fast_mlsirm_components", lambda: None
    )
    capped = replace(PAID, max_output_tokens=200)
    client = ModelClient()
    client.token_counter = _ExactCounter()

    def transport(agent, messages, temperature=None, top_p=None, effort_profile=None):
        client._local.usage = {"prompt_tokens": 100, "completion_tokens": 50}
        return "answer"

    client._chat_transport = transport  # type: ignore[method-assign]
    assert client._admission_token_bounds(capped, PROMPT) == AdmissionTokenBounds(
        100, 200
    )
    guard = SpendGuard(
        config=SpendGuardConfig.from_values(run_max_cost_usd=1),
        price_book=_price_book(),
    )
    orch = TaskOrchestrator(
        [capped], client=client, spend_guard=guard, rate_limit_wait_seconds=0.0
    )
    orch.policy = replace(orch.policy, realtime_judge=False)
    result = orch.route_once(PROMPT)
    assert result["answer"] == "answer"
    assert guard.last_run_summary()["budget"]["refusals"] == []

    # Without an exact counter the $4 context ceiling refuses under the $1 cap.
    client.token_counter = object()
    assert client._admission_token_bounds(capped, PROMPT) == AdmissionTokenBounds(
        None, 200
    )
    with pytest.raises(BudgetExceededError):
        orch.route_once(PROMPT)
    refusal = guard.last_run_summary()["budget"]["refusals"][0]
    assert refusal["estimate_source"] == "context_window_ceiling"
