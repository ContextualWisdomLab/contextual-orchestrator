"""Per-run spend guard, provider drop, and tenant budgets through TaskOrchestrator (ADR 0138).

Every provider is faked: the transport seam (``ModelClient._chat_transport``)
is replaced in-process or served by a local SSE server, so no live or paid
provider is ever called.
"""

from __future__ import annotations

from dataclasses import replace
from contextvars import copy_context
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import threading
import urllib.error

import pytest

from contextual_orchestrator import orchestrator as orchestrator_module
from contextual_orchestrator.cost_ledger import PriceBook, PriceEntry
from contextual_orchestrator.domain.budget import BudgetExceededError, CallPurpose
from contextual_orchestrator.kv_config import InMemoryConfigStore
from contextual_orchestrator.orchestrator import ModelAgent, ModelClient, TaskOrchestrator
from contextual_orchestrator.provider_errors import ProviderUpstreamError, classify_provider_failure
from contextual_orchestrator.spend_guard import (
    PROVIDER_BUDGET_EXHAUSTED_CODE,
    ProviderBudgetExhaustedError,
    SpendGuard,
    SpendGuardConfig,
    VirtualKeyError,
    guarded_provider_call,
    raise_if_stream_limit_event,
)
from contextual_orchestrator.spend_metering import InMemorySpendLedgerStore, JsonlSpendLedgerStore

PAID = ModelAgent(
    "openai_paid_agent",
    "gpt-paid",
    base_url="https://api.openai.test/v1",
    provider_name="openai",
    context_window=2000,
)
BACKUP = ModelAgent(
    "openrouter_backup_agent",
    "llama-backup",
    base_url="https://openrouter.test/api/v1",
    provider_name="openrouter",
    context_window=2000,
)
UNPRICED = ModelAgent("bytez_unpriced_agent", "bytez-model", base_url="https://api.bytez.test/v1", provider_name="bytez")
USAGE = {"prompt_tokens": 1000, "completion_tokens": 1000}
PROMPT = [{"role": "user", "content": "hello there"}]


def _price_book() -> PriceBook:
    book = PriceBook(InMemoryConfigStore())
    book.set_price(PriceEntry("openai", "gpt-paid", 1.0, 1.0))  # $2 per USAGE call
    book.set_price(PriceEntry("openrouter", "llama-backup", 0.1, 0.1))  # $0.20 per USAGE call
    return book


def _http_error(status: int, payload: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://provider.test/v1/chat/completions", status, "error", {},
        io.BytesIO(json.dumps(payload).encode()),
    )


class _FakeTransport:
    """Scripted per-provider replies installed as ``ModelClient._chat_transport``."""

    def __init__(self, client: ModelClient, behaviour: dict[str, object]) -> None:
        self.client = client
        self.behaviour = behaviour
        self.calls: list[str] = []

    def __call__(self, agent, messages, temperature=None, top_p=None, effort_profile=None):
        self.calls.append(agent.provider_name)
        reply = self.behaviour[agent.provider_name]
        if isinstance(reply, BaseException):
            self.client._local.usage = None
            raise classify_provider_failure(reply, agent_id=agent.id, model=agent.model)
        self.client._local.usage = dict(USAGE)
        return str(reply)


def _orchestrator(agents, behaviour, *, guard: SpendGuard | None = None):
    client = ModelClient()
    transport = _FakeTransport(client, behaviour)
    client._chat_transport = transport  # type: ignore[method-assign]
    guard = guard or SpendGuard(price_book=_price_book())
    orch = TaskOrchestrator(list(agents), client=client, spend_guard=guard, rate_limit_wait_seconds=0.0)
    orch.policy = replace(orch.policy, realtime_judge=False)
    return orch, transport, guard


@pytest.fixture(autouse=True)
def _no_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator_module, "_resolve_fast_mlsirm_components", lambda: None)


# -- defaults ----------------------------------------------------------------

def test_default_config_has_no_run_cap_or_heuristic_baseline_threshold() -> None:
    """The default adds neither a cap nor a numeric baseline admission rule."""
    config = SpendGuardConfig()
    assert config.run_max_cost is None
    assert not hasattr(config, "baseline_min_remaining_ratio")
    store = InMemoryConfigStore()
    store.set("spend_guard_settings", "run_max_cost_usd", "2.5")
    assert SpendGuardConfig.from_config_store(store).run_max_cost.as_float() == 2.5


def test_orchestrator_defaults_to_an_uncapped_guard_on_mock_agents() -> None:
    """Existing mock deployments keep working and still get metered."""
    orch = TaskOrchestrator([ModelAgent("general_agent", "m-model")])
    orch.policy = replace(orch.policy, realtime_judge=False)
    result = orch.route_once(PROMPT)
    assert result["answer"]
    summary = orch.spend_guard.last_run_summary()
    assert summary["tenant_id"] == "default"
    assert summary["calls"][0]["cost_source"] == "zero_cost"


def test_calls_outside_a_run_scope_are_untouched() -> None:
    """Direct ModelClient use without a run scope bypasses the guard."""
    assert guarded_provider_call(PAID, PROMPT, lambda: "ok", usage_reader=None) == "ok"


# -- run cap -----------------------------------------------------------------

def test_run_cap_meters_and_stops_further_calls_in_the_same_run() -> None:
    """After the cap is spent, the next provider call is refused before it is sent."""
    guard = SpendGuard(config=SpendGuardConfig.from_values(run_max_cost_usd=2), price_book=_price_book())
    orch, transport, _ = _orchestrator([PAID], {"openai": "answer"}, guard=guard)
    with guard.run_scope("run_cap_test") as scope:
        orch.route_once(PROMPT)
        assert scope.spent.as_float() == 2.0
        with pytest.raises(BudgetExceededError) as refused:
            orch.route_once(PROMPT)
    assert transport.calls == ["openai"]
    assert refused.value.detail["reason"] == "budget_exhausted"
    assert refused.value.detail["scope"] == "run"
    assert guard.last_run_summary()["budget"]["refusals"][0]["provider_name"] == "openai"


def test_run_cap_refuses_paid_call_without_a_total_cost_upper_bound() -> None:
    """A provider context ceiling bounds total tokens and prevents cap overshoot."""
    guard = SpendGuard(
        config=SpendGuardConfig.from_values(run_max_cost_usd="1.5"),
        price_book=_price_book(),
    )
    orch, transport, _ = _orchestrator([PAID], {"openai": "answer"}, guard=guard)

    with pytest.raises(BudgetExceededError) as refused:
        orch.route_once(PROMPT)

    assert refused.value.detail["reason"] == "insufficient_remaining_budget"
    assert transport.calls == []


def test_run_cap_fails_closed_when_total_token_ceiling_is_unknown() -> None:
    """A priced route without an authoritative total-token ceiling is inadmissible."""
    guard = SpendGuard(
        config=SpendGuardConfig.from_values(run_max_cost_usd="100"),
        price_book=_price_book(),
    )
    unbounded = replace(PAID, context_window=None)
    orch, transport, _ = _orchestrator([unbounded], {"openai": "answer"}, guard=guard)

    with pytest.raises(BudgetExceededError) as refused:
        orch.route_once(PROMPT)

    assert refused.value.detail["reason"] == "cost_upper_bound_unavailable"
    assert transport.calls == []


def test_run_cap_reserves_in_flight_upper_bounds_atomically() -> None:
    """Two branches cannot both consume the same remaining run headroom."""
    guard = SpendGuard(
        config=SpendGuardConfig.from_values(run_max_cost_usd="3"),
        price_book=_price_book(),
    )
    state = threading.Condition()
    provider_calls: list[str] = []
    outcomes: list[object] = []
    release = threading.Event()

    def provider_call() -> str:
        with state:
            provider_calls.append("openai")
            state.notify_all()
        release.wait()
        return "answer"

    def worker(context) -> None:
        try:
            result = context.run(
                guarded_provider_call,
                PAID,
                PROMPT,
                provider_call,
                usage_reader=lambda: USAGE,
            )
            outcome: object = result
        except Exception as exc:  # noqa: BLE001 - the refusal is the observed outcome
            outcome = exc
        with state:
            outcomes.append(outcome)
            state.notify_all()

    with guard.run_scope() as scope:
        first = threading.Thread(target=worker, args=(copy_context(),))
        first.start()
        with state:
            state.wait_for(lambda: len(provider_calls) == 1)
        second = threading.Thread(target=worker, args=(copy_context(),))
        second.start()
        with state:
            state.wait_for(lambda: len(provider_calls) == 2 or bool(outcomes))
        release.set()
        first.join()
        second.join()

    assert provider_calls == ["openai"]
    assert sum(isinstance(item, BudgetExceededError) for item in outcomes) == 1
    assert scope.spent.as_float() == 2.0


def test_unknown_failure_cost_consumes_the_reserved_upper_bound() -> None:
    """A post-admission failure cannot release unmeasured spend as if it were free."""
    guard = SpendGuard(
        config=SpendGuardConfig.from_values(run_max_cost_usd="10"),
        price_book=_price_book(),
    )
    calls: list[str] = []

    def failed_call() -> str:
        calls.append("failed")
        raise RuntimeError("provider outcome unknown")

    with guard.run_scope() as scope:
        with pytest.raises(RuntimeError, match="outcome unknown"):
            guarded_provider_call(PAID, PROMPT, failed_call, usage_reader=None)
        with pytest.raises(BudgetExceededError) as refused:
            guarded_provider_call(
                PAID,
                PROMPT,
                lambda: calls.append("unexpected") or "answer",
                usage_reader=None,
            )

    assert scope.spent.as_float() == 2.0
    assert scope.measurement_complete is False
    assert refused.value.detail["reason"] == "measurement_unavailable"
    assert calls == ["failed"]


def test_tenant_budget_reserves_across_concurrent_run_scopes() -> None:
    """Separate runs sharing a store cannot spend the same tenant headroom."""
    store = InMemorySpendLedgerStore()
    guard = SpendGuard(price_book=_price_book(), store=store)
    guard.set_tenant_budget("acme", max_budget_usd="3")
    state = threading.Condition()
    release = threading.Event()
    provider_calls: list[str] = []
    outcomes: list[object] = []

    def provider_call() -> str:
        with state:
            provider_calls.append("openai")
            state.notify_all()
        release.wait()
        return "answer"

    def worker() -> None:
        try:
            with guard.tenant_context(tenant_id="acme"), guard.run_scope():
                outcome: object = guarded_provider_call(
                    PAID,
                    PROMPT,
                    provider_call,
                    usage_reader=lambda: USAGE,
                )
        except Exception as exc:  # noqa: BLE001 - refusal is the observed outcome
            outcome = exc
        with state:
            outcomes.append(outcome)
            state.notify_all()

    first = threading.Thread(target=worker)
    first.start()
    with state:
        state.wait_for(lambda: len(provider_calls) == 1)
    second = threading.Thread(target=worker)
    second.start()
    with state:
        state.wait_for(lambda: len(provider_calls) == 2 or bool(outcomes))
    release.set()
    first.join()
    second.join()

    assert provider_calls == ["openai"]
    assert sum(isinstance(item, BudgetExceededError) for item in outcomes) == 1


def test_jsonl_unknown_outcome_reservation_survives_a_new_store_instance(
    tmp_path: Path,
) -> None:
    """An unmeasured call remains budgeted after another process reloads the ledger."""
    ledger_path = tmp_path / "ledger.jsonl"
    first_guard = SpendGuard(
        price_book=_price_book(),
        store=JsonlSpendLedgerStore(ledger_path),
    )
    first_guard.set_tenant_budget("acme", max_budget_usd="3")

    with first_guard.tenant_context(tenant_id="acme"), first_guard.run_scope():
        with pytest.raises(RuntimeError, match="outcome unknown"):
            guarded_provider_call(
                PAID,
                PROMPT,
                lambda: (_ for _ in ()).throw(RuntimeError("provider outcome unknown")),
                usage_reader=None,
            )

    second_guard = SpendGuard(
        price_book=_price_book(),
        store=JsonlSpendLedgerStore(ledger_path),
    )
    provider_calls: list[str] = []
    with second_guard.tenant_context(tenant_id="acme"), second_guard.run_scope():
        with pytest.raises(BudgetExceededError) as refused:
            guarded_provider_call(
                PAID,
                PROMPT,
                lambda: provider_calls.append("unexpected") or "answer",
                usage_reader=lambda: USAGE,
            )

    assert refused.value.detail["reason"] == "insufficient_remaining_budget"
    assert provider_calls == []


def test_existing_spend_budget_check_consults_the_run_scope() -> None:
    """``_raise_if_spend_budget_exceeded`` is extended, not duplicated."""
    guard = SpendGuard(config=SpendGuardConfig.from_values(run_max_cost_usd=2), price_book=_price_book())
    orch, _, _ = _orchestrator([PAID], {"openai": "answer"}, guard=guard)
    with guard.run_scope():
        orch._raise_if_spend_budget_exceeded()
        orch.route_once(PROMPT)
        with pytest.raises(BudgetExceededError):
            orch._raise_if_spend_budget_exceeded()


def test_unknown_price_fails_closed_only_when_capped() -> None:
    """An unpriced paid provider is refused under a cap and allowed without one."""
    capped = SpendGuard(config=SpendGuardConfig.from_values(run_max_cost_usd=5), price_book=_price_book())
    orch, transport, _ = _orchestrator([UNPRICED], {"bytez": "answer"}, guard=capped)
    with pytest.raises(BudgetExceededError, match="price_unknown"):
        orch.route_once(PROMPT)
    assert transport.calls == []
    orch2, transport2, guard2 = _orchestrator([UNPRICED], {"bytez": "answer"})
    orch2.route_once(PROMPT)
    assert transport2.calls == ["bytez"]
    call = guard2.last_run_summary()["calls"][0]
    assert call["price_unknown"] is True and call["charged_cost_usd"] is None


def test_provider_reported_cost_wins_over_price_book() -> None:
    """``usage.cost`` from the provider is charged instead of the catalogue estimate."""
    orch, transport, guard = _orchestrator([PAID], {"openai": "answer"})

    def reply(agent, messages, temperature=None, top_p=None, effort_profile=None):
        orch.client._local.usage = {**USAGE, "cost": 0.0042}
        return "answer"

    orch.client._chat_transport = reply  # type: ignore[method-assign]
    orch.route_once(PROMPT)
    call = guard.last_run_summary()["calls"][0]
    assert call["cost_source"] == "provider_reported"
    assert call["charged_cost_usd"] == pytest.approx(0.0042)


# -- provider drop ------------------------------------------------------------

def test_spend_limit_drops_only_that_provider_and_the_run_continues() -> None:
    """OpenAI's project spend limit drops OpenAI; OpenRouter serves this and later calls."""
    limit = _http_error(429, {"error": {"code": "project_spend_limit_exceeded", "message": "x"}})
    orch, transport, guard = _orchestrator([PAID, BACKUP], {"openai": limit, "openrouter": "backup answer"})
    with guard.run_scope() as scope:
        first = orch.route_once(PROMPT)
        second = orch.route_once(PROMPT)
    assert first["answer"] == second["answer"] == "backup answer"
    assert transport.calls.count("openai") <= 1
    assert scope.dropped_providers == {"openai": "project_spend_limit_exceeded"}
    summary = guard.last_run_summary()
    statuses = {call["record"]["provider_name"]: call["call_status"] for call in summary["calls"]}
    assert statuses.get("openrouter") == "ok"


def test_openrouter_zero_balance_402_drops_only_openrouter_without_retry_or_cost() -> None:
    """A zero account balance (402 ``openrouter_credits``) drops OpenRouter only.

    ``/api/v1/key`` ``limit_remaining`` is the key's cap, not the account
    balance, so discovery can admit paid models that then hit this 402. It is
    not retried, costs nothing, and the run continues on another provider.
    """
    zero_balance = _http_error(
        402,
        {"error": {"code": 402, "message": "Insufficient credits", "metadata": {"limit_source": "openrouter_credits"}}},
    )
    openrouter_first = replace(BACKUP, priority=10)
    openai_backup = replace(PAID, priority=0)
    orch, transport, guard = _orchestrator(
        [openrouter_first, openai_backup], {"openrouter": zero_balance, "openai": "openai answer"}
    )
    with guard.run_scope() as scope:
        first = orch.route_once(PROMPT)
        second = orch.route_once(PROMPT)
    assert first["answer"] == second["answer"] == "openai answer"
    assert transport.calls.count("openrouter") == 1
    assert scope.dropped_providers == {"openrouter": "openrouter_credits"}
    refused = [entry for entry in scope.entries if entry.record.provider_name == "openrouter"]
    assert all(entry.cost_source == "zero_cost" and entry.charged_cost.amount == 0 for entry in refused)


def test_openrouter_in_flight_budget_402_is_temporary_not_a_drop() -> None:
    """Only the in-flight-budget 402 stays temporary: OpenRouter remains in the run."""
    in_flight = _http_error(
        402, {"error": {"code": 402, "metadata": {"limit_source": "openrouter_in_flight_budget"}}}
    )
    orch, transport, guard = _orchestrator(
        [replace(BACKUP, priority=10), PAID], {"openrouter": in_flight, "openai": "ok"}
    )
    with guard.run_scope() as scope:
        orch.route_once(PROMPT)
    assert transport.calls[0] == "openrouter"
    assert scope.dropped_providers == {}


def test_plain_rate_limit_does_not_drop_the_provider() -> None:
    """A normal 429 leaves the provider available for the rest of the run."""
    rate = _http_error(429, {"error": {"code": "rate_limit_exceeded"}})
    orch, transport, guard = _orchestrator([PAID, BACKUP], {"openai": rate, "openrouter": "ok"})
    with guard.run_scope() as scope:
        orch.route_once(PROMPT)
    assert transport.calls[0] == "openai"
    assert scope.dropped_providers == {}


def test_all_providers_dropped_fails_closed() -> None:
    """With every provider exhausted the run fails, and no further call is sent."""
    orch, transport, guard = _orchestrator(
        [PAID, BACKUP],
        {
            "openai": _http_error(429, {"error": {"code": "insufficient_quota"}}),
            "openrouter": _http_error(402, {"error": {"code": 402, "metadata": {"limit_source": "openrouter_credits"}}}),
        },
    )
    with guard.run_scope() as scope:
        with pytest.raises(Exception) as first:
            orch.route_once(PROMPT)
        sent = len(transport.calls)
        with pytest.raises(Exception) as second:
            orch.route_once(PROMPT)
    assert not isinstance(first.value, BudgetExceededError)
    assert set(scope.dropped_providers) == {"openai", "openrouter"}
    assert len(transport.calls) == sent
    assert "exhausted" in str(second.value) or getattr(second.value, "error_code", "") in {
        PROVIDER_BUDGET_EXHAUSTED_CODE, "payment_required",
    }


def test_drop_error_is_non_retryable_and_never_a_rate_limit() -> None:
    """The typed drop error cannot trigger rate-limit cooldown or storm-wait."""
    guard = SpendGuard(price_book=_price_book())
    limit = classify_provider_failure(
        _http_error(429, {"error": {"code": "organization_spend_limit_exceeded"}}), agent_id="a", model="m"
    )

    def call():
        raise limit

    with guard.run_scope():
        with pytest.raises(ProviderBudgetExhaustedError) as caught:
            guarded_provider_call(PAID, PROMPT, call, usage_reader=None)
    error = caught.value
    assert error.retryable is False and error.provider_status is None
    assert error.error_code == PROVIDER_BUDGET_EXHAUSTED_CODE and error.client_status == 402
    assert error.extra_detail["limit_provider_status"] == 429


def test_in_stream_limit_event_raises_only_for_limit_errors() -> None:
    """A mid-stream error object inside HTTP 200 is classified like a status error."""
    raise_if_stream_limit_event(BACKUP, {"choices": [{"delta": {"content": "x"}}]})
    raise_if_stream_limit_event(BACKUP, {"error": {"code": 500, "message": "boom"}})
    with pytest.raises(ProviderUpstreamError) as caught:
        raise_if_stream_limit_event(
            BACKUP, {"error": {"code": 402, "metadata": {"limit_source": "openrouter_key_limit"}}}
        )
    assert caught.value.limit_evidence["limit_source"] == "openrouter_key_limit"


class _SSEProvider:
    """Local SSE server: a first delta, then an in-stream limit error inside HTTP 200."""

    def __init__(self, frames: list[str]) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("content-length", 0)))
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                for frame in frames:
                    self.wfile.write(frame.encode())
                    self.wfile.flush()

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "_SSEProvider":
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    @property
    def base_url(self) -> str:
        return f"local://127.0.0.1:{self.server.server_address[1]}"


def test_mid_stream_limit_error_in_http_200_drops_the_provider() -> None:
    """The real SSE transport raises on the in-stream error and the run drops that provider."""
    error_frame = {"error": {"code": 402, "message": "no credits", "metadata": {"limit_source": "openrouter_credits"}}}
    frames = [
        'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
        "data: " + json.dumps(error_frame) + "\n\n",
        "data: [DONE]\n\n",
    ]
    with _SSEProvider(frames) as provider:
        agent = ModelAgent("openrouter_stream_agent", "llama", base_url=provider.base_url, provider_name="openrouter")
        client = ModelClient()
        guard = SpendGuard(price_book=_price_book())
        with guard.run_scope() as scope:
            with pytest.raises(ProviderUpstreamError) as caught:
                list(client.stream_chat(agent, PROMPT))
    assert scope.dropped_providers == {"openrouter": "openrouter_credits"}
    assert caught.value.retryable is False
    assert [call.call_status for call in scope.entries] == ["provider_limit"]
    # Output may already have been billed mid-stream: the cost stays unknown.
    assert scope.entries[0].cost_source in {"unknown", "zero_cost"}


# -- baselines -----------------------------------------------------------------

def test_baseline_is_skipped_first_and_charged_to_the_same_guard() -> None:
    """compare_to_baseline drops the sampled baseline when headroom runs short."""
    guard = SpendGuard(
        config=SpendGuardConfig.from_values(run_max_cost_usd=3),
        price_book=_price_book(),
    )
    orch, transport, _ = _orchestrator([PAID], {"openai": "answer"}, guard=guard)
    report = orch.compare_to_baseline(["compare this prompt"], mode="route")
    assert report["aggregate"]["baseline_skipped_count"] == 1
    assert report["results"][0]["baseline"] == {"skipped": True, "reason": "spend_budget"}
    assert all(call["purpose"] == "primary" for call in guard.last_run_summary()["calls"])


def test_baseline_runs_with_headroom_and_is_tagged() -> None:
    """Without a hard cap the baseline runs and is metered as baseline spend."""
    guard = SpendGuard(price_book=_price_book())
    orch, _, _ = _orchestrator([PAID], {"openai": "answer"}, guard=guard)
    report = orch.compare_to_baseline(["compare this prompt"], mode="route")
    assert report["aggregate"]["baseline_skipped_count"] == 0
    purposes = [call["purpose"] for call in guard.last_run_summary()["calls"]]
    assert CallPurpose.BASELINE.value in purposes and CallPurpose.PRIMARY.value in purposes


# -- virtual keys and tenant budgets ---------------------------------------------

def test_virtual_key_budget_is_enforced_across_runs(tmp_path: Path) -> None:
    """A key's max_budget accumulates across runs and refuses once spent."""
    store = JsonlSpendLedgerStore(tmp_path / "ledger.jsonl")
    guard = SpendGuard(price_book=_price_book(), store=store)
    secret, key = guard.issue_virtual_key("acme", max_budget_usd=2, budget_duration="30d")
    orch, transport, _ = _orchestrator([PAID], {"openai": "answer"}, guard=guard)
    with guard.tenant_context(virtual_key=secret):
        orch.route_once(PROMPT)
        with pytest.raises(BudgetExceededError) as refused:
            orch.route_once(PROMPT)
    assert refused.value.detail["scope"] == "virtual_key"
    assert refused.value.detail["tenant_id"] == "acme"
    assert refused.value.detail["virtual_key_id"] == key.key_id
    assert refused.value.detail["budget_reset_at"] == key.created_at + 30 * 86400
    assert transport.calls == ["openai"]
    assert secret not in (tmp_path / "ledger.jsonl").read_text()


def test_unknown_or_foreign_virtual_key_is_rejected() -> None:
    """Keys must exist, be enabled, and match any asserted tenant."""
    guard = SpendGuard(store=InMemorySpendLedgerStore())
    secret, _ = guard.issue_virtual_key("acme")
    with pytest.raises(VirtualKeyError):
        guard.resolve_identity(virtual_key="sk-co-" + "z" * 40)
    with pytest.raises(VirtualKeyError):
        guard.resolve_identity(tenant_id="globex", virtual_key=secret)
    assert guard.resolve_identity(virtual_key=secret)[0] == "acme"
    assert guard.resolve_identity(tenant_id="globex") == ("globex", None)
    assert guard.resolve_identity() == ("default", None)
    with pytest.raises(VirtualKeyError):
        SpendGuard().resolve_identity(virtual_key=secret)


def test_tenant_budget_applies_to_every_key_of_the_tenant() -> None:
    """Keys attached to a tenant are bounded by the shared tenant budget."""
    guard = SpendGuard(price_book=_price_book(), store=InMemorySpendLedgerStore())
    guard.set_tenant_budget("acme", max_budget_usd=3)
    first_key, _ = guard.issue_virtual_key("acme", max_budget_usd=100)
    second_key, _ = guard.issue_virtual_key("acme", max_budget_usd=100)
    orch, _, _ = _orchestrator([PAID], {"openai": "answer"}, guard=guard)
    with guard.tenant_context(virtual_key=first_key):
        orch.route_once(PROMPT)
    with guard.tenant_context(virtual_key=second_key):
        with pytest.raises(BudgetExceededError) as refused:
            orch.route_once(PROMPT)
    assert refused.value.detail["scope"] == "tenant"
    with guard.tenant_context(tenant_id="globex"):
        orch.route_once(PROMPT)


def test_tightest_of_run_key_and_tenant_wins_through_the_orchestrator() -> None:
    """The run cap binds before a looser key and tenant budget."""
    guard = SpendGuard(
        config=SpendGuardConfig.from_values(run_max_cost_usd=2),
        price_book=_price_book(),
        store=InMemorySpendLedgerStore(),
    )
    guard.set_tenant_budget("acme", max_budget_usd=50)
    secret, _ = guard.issue_virtual_key("acme", max_budget_usd=20)
    orch, _, _ = _orchestrator([PAID], {"openai": "answer"}, guard=guard)
    with guard.tenant_context(virtual_key=secret), guard.run_scope():
        orch.route_once(PROMPT)
        with pytest.raises(BudgetExceededError) as refused:
            orch.route_once(PROMPT)
    assert refused.value.detail["scope"] == "run"


def test_soft_budget_logs_once_without_blocking(caplog: pytest.LogCaptureFixture) -> None:
    """A soft budget warns but never refuses."""
    guard = SpendGuard(price_book=_price_book(), store=InMemorySpendLedgerStore())
    secret, _ = guard.issue_virtual_key("acme", soft_budget_usd=1)
    orch, transport, _ = _orchestrator([PAID], {"openai": "answer"}, guard=guard)
    with caplog.at_level("WARNING"), guard.tenant_context(virtual_key=secret), guard.run_scope():
        for _ in range(3):
            orch.route_once(PROMPT)
    assert transport.calls == ["openai"] * 3
    assert sum("soft budget crossed" in record.message for record in caplog.records) == 1


# -- artifact -------------------------------------------------------------------

def test_run_summary_lists_calls_budgets_and_drops() -> None:
    """The per-run artifact reports usage, cost completeness, limits, and dropped providers."""
    limit = _http_error(402, {"error": "Payment Required", "status": 402})
    bytez = replace(UNPRICED, id="bytez_paid_agent", context_window=1000)
    guard = SpendGuard(config=SpendGuardConfig.from_values(run_max_cost_usd=10), price_book=_price_book())
    guard.price_book.set_price(PriceEntry("bytez", "bytez-model", 0.01, 0.01))
    orch, _, _ = _orchestrator([bytez, BACKUP], {"bytez": limit, "openrouter": "ok"}, guard=guard)
    orch.route_once(PROMPT)
    summary = guard.last_run_summary()
    assert summary["schema"] == "contextual_orchestrator.run_usage_summary.v1"
    assert summary["budget"]["run_max_cost"] == 10.0
    assert summary["dropped_providers"] == {"bytez": "bytez_insufficient_credits"}
    calls = {call["record"]["provider_name"]: call for call in summary["calls"]}
    assert calls["openrouter"]["cost_source"] == "price_book"
    # A pre-response 402 refusal is not billed: charged zero, not unknown.
    assert calls["bytez"]["call_status"] == "provider_limit"
    assert calls["bytez"]["cost_source"] == "zero_cost"
    assert summary["totals"][0]["cost_complete"] is True
    json.dumps(summary)


def test_run_cap_stops_conduct_before_the_next_paid_call() -> None:
    """Multi-step conduct shares one run budget and fails closed once it is spent."""
    guard = SpendGuard(config=SpendGuardConfig.from_values(run_max_cost_usd=2), price_book=_price_book())
    orch, transport, _ = _orchestrator([PAID], {"openai": "answer"}, guard=guard)
    with pytest.raises(BudgetExceededError):
        orch.conduct(PROMPT)
    assert transport.calls == ["openai"]


def test_stream_route_runs_inside_a_run_scope() -> None:
    """Streaming routes are metered and the scope never leaks to the consumer."""
    orch = TaskOrchestrator([ModelAgent("general_agent", "m-model", tags=("reasoning", "writing"))])
    deltas = []
    for delta in orch.stream_route(PROMPT):
        assert SpendGuard.active_scope() is None
        deltas.append(delta)
    assert "".join(deltas)
    summary = orch.spend_guard.last_run_summary()
    assert [call["record"]["request_channel"] for call in summary["calls"]] == ["stream"]
